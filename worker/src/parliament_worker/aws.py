"""Opt-in S3 preservation and at-least-once SQS outbox/inbox adapters."""

import hashlib
import json
import logging
import re
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

LOGGER = logging.getLogger(__name__)


def aws_client(service: str) -> Any:
    """Create an optional AWS SDK client using roles or configured SSO chain."""
    try:
        import boto3
    except ImportError as error:
        raise RuntimeError("install the optional aws dependency group") from error
    return boto3.client(service, region_name="ap-northeast-2")


def validate_queue_url(value: str) -> str:
    """Accept only explicit AWS Seoul-region SQS queue URLs."""
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "sqs.ap-northeast-2.amazonaws.com"
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.query
        or parsed.fragment
        or not re.fullmatch(r"/\d{12}/[A-Za-z0-9_-]+(?:\.fifo)?", parsed.path)
    ):
        raise ValueError("invalid configured SQS queue URL")
    return value


class S3RawStore:
    """Preserve immutable raw blobs using conditional S3 writes, IAM and SSE."""

    def __init__(
        self, bucket: str, *, client: Any = None, enabled: bool = False
    ) -> None:
        if not enabled:
            raise ValueError("S3 requires explicit opt-in")
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket):
            raise ValueError("invalid configured S3 bucket")
        self.bucket = bucket
        self.client = client or aws_client("s3")

    def save(self, source_key: str, record_key: str, raw: bytes) -> str:
        """Conditionally write one content-addressed blob; retries do not overwrite."""
        identity = hashlib.sha256(f"{source_key}:{record_key}".encode()).hexdigest()
        digest = hashlib.sha256(raw).hexdigest()
        key = f"parliament/raw/{identity}/{digest}.bin"
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=raw,
                IfNoneMatch="*",
                ServerSideEncryption="AES256",
                ContentType="application/octet-stream",
            )
        except Exception as error:
            response = getattr(error, "response", {})
            if response.get("Error", {}).get("Code") not in (
                "PreconditionFailed",
                "412",
            ):
                raise
        return key


class OutboxRepository(Protocol):
    """Database access to Java's transactional processing outbox."""

    def pending(self, limit: int) -> list[dict[str, Any]]:
        """Read pending/retryable identities in creation order."""
        ...

    def mark_sent(self, outbox_id: int) -> None:
        """Commit a successfully dispatched message."""
        ...

    def mark_failed(self, outbox_id: int, error: str) -> None:
        """Commit a retryable failure without sensitive exception detail."""
        ...


def validate_version_message(message: dict[str, Any]) -> dict[str, Any]:
    """Reject invalid versions and extra data before queue/network processing."""
    if set(message) != {"outboxId", "sourceKey", "recordKey", "payloadHash"}:
        raise ValueError("invalid version message fields")
    if (
        not isinstance(message["outboxId"], int)
        or isinstance(message["outboxId"], bool)
        or message["outboxId"] <= 0
    ):
        raise ValueError("invalid outbox identity")
    for name, maximum in (("sourceKey", 100), ("recordKey", 255)):
        value = message[name]
        if (
            not isinstance(value, str)
            or not 1 <= len(value) <= maximum
            or any(ord(char) < 32 for char in value)
        ):
            raise ValueError("invalid source identity")
    if not isinstance(message["payloadHash"], str) or not re.fullmatch(
        r"(?:[a-f0-9]{40}|[a-f0-9]{64})", message["payloadHash"]
    ):
        raise ValueError("invalid source version")
    return message


class SqsOutboxRelay:
    """Dispatch metadata only; a send/commit crash safely produces duplicates."""

    def __init__(
        self,
        repository: OutboxRepository,
        queue_url: str,
        *,
        client: Any = None,
        enabled: bool = False,
    ) -> None:
        if not enabled:
            raise ValueError("SQS relay requires explicit opt-in")
        self.repository = repository
        self.queue_url = validate_queue_url(queue_url)
        self.client = client or aws_client("sqs")

    def run(self, limit: int = 20) -> int:
        """Dispatch a bounded batch and retain failures for the next run."""
        if not 1 <= limit <= 100:
            raise ValueError("invalid relay batch size")
        count = 0
        for row in self.repository.pending(limit):
            try:
                message = validate_version_message(
                    {
                        "outboxId": int(row["outbox_id"]),
                        "sourceKey": row["source_key"],
                        "recordKey": row["record_key"],
                        "payloadHash": row["payload_hash"],
                    }
                )
                options = {
                    "QueueUrl": self.queue_url,
                    "MessageBody": json.dumps(message, separators=(",", ":")),
                }
                if self.queue_url.endswith(".fifo"):
                    options["MessageGroupId"] = "parliament-processing"
                    options["MessageDeduplicationId"] = hashlib.sha256(
                        options["MessageBody"].encode()
                    ).hexdigest()
                self.client.send_message(**options)
                self.repository.mark_sent(int(row["outbox_id"]))
                count += 1
            except Exception as error:
                self.repository.mark_failed(int(row["outbox_id"]), type(error).__name__)
        return count


class SqsVersionConsumer:
    """Acknowledge only successful processing and retain durable version dedup."""

    def __init__(
        self,
        queue_url: str,
        ledger: Path,
        process: Callable[[dict[str, Any]], Any],
        *,
        client: Any = None,
        enabled: bool = False,
    ) -> None:
        if not enabled:
            raise ValueError("SQS consume requires explicit opt-in")
        self.queue_url = validate_queue_url(queue_url)
        self.client = client or aws_client("sqs")
        self.process = process
        ledger.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(ledger, isolation_level=None)
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS processed_versions(identity TEXT PRIMARY KEY)"
        )

    def run_once(self) -> int:
        """Process at most ten messages; failed callbacks leave messages unacked."""
        response = self.client.receive_message(
            QueueUrl=self.queue_url,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=1,
            VisibilityTimeout=120,
        )
        count = 0
        for envelope in response.get("Messages", []):
            try:
                if len(envelope["Body"]) > 4096:
                    raise ValueError("message too large")
                message = validate_version_message(json.loads(envelope["Body"]))
                identity = hashlib.sha256(
                    json.dumps(
                        [
                            message["sourceKey"],
                            message["recordKey"],
                            message["payloadHash"],
                        ]
                    ).encode()
                ).hexdigest()
                self.connection.execute("BEGIN IMMEDIATE")
                if not self.connection.execute(
                    "SELECT 1 FROM processed_versions WHERE identity=?", (identity,)
                ).fetchone():
                    self.process(message)
                    self.connection.execute(
                        "INSERT INTO processed_versions VALUES (?)", (identity,)
                    )
                    count += 1
                self.connection.commit()
                self.client.delete_message(
                    QueueUrl=self.queue_url, ReceiptHandle=envelope["ReceiptHandle"]
                )
            except Exception as error:
                self.connection.rollback()
                LOGGER.warning(
                    "SQS processing retained for retry (%s)", type(error).__name__
                )
        return count

    def close(self) -> None:
        """Close the durable inbox ledger."""
        self.connection.close()
