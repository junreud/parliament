"""DB-API adapters for the Java raw-version/outbox tables; no schema mutation."""

import json
import os
from pathlib import Path
from typing import Any

from parliament_worker.aws import aws_client, validate_version_message


class MySqlOutbox:
    """Read source versions and explicitly update outbox dispatch status."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def pending(self, limit: int) -> list[dict[str, Any]]:
        """Read PENDING/FAILED metadata; duplicate delivery is expected and safe."""
        if not 1 <= limit <= 100:
            raise ValueError("invalid outbox batch size")
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT outbox_id,source_key,record_key,payload_hash FROM parliament_processing_outbox WHERE status IN ('PENDING','FAILED') AND attempts<5 ORDER BY created_at,outbox_id LIMIT %s",
                (limit,),
            )
            return list(cursor.fetchall())

    def mark_sent(self, outbox_id: int) -> None:
        """Commit the SENT state only after SQS accepts the message."""
        with self.connection.cursor() as cursor:
            cursor.execute(
                "UPDATE parliament_processing_outbox SET status='SENT',attempts=attempts+1,last_error=NULL WHERE outbox_id=%s",
                (outbox_id,),
            )
        self.connection.commit()

    def mark_failed(self, outbox_id: int, error: str) -> None:
        """Persist a failure category without exception text, payloads or secrets."""
        with self.connection.cursor() as cursor:
            cursor.execute(
                "UPDATE parliament_processing_outbox SET status='FAILED',attempts=attempts+1,last_error=%s WHERE outbox_id=%s",
                (error[:255], outbox_id),
            )
        self.connection.commit()

    def version(self, message: dict[str, Any]) -> dict[str, Any]:
        """Read the exact immutable version identified by an SQS message."""
        validate_version_message(message)
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT source_key,record_key,payload_hash,api_code,raw_payload,observed_at FROM parliament_source_record_version WHERE source_key=%s AND record_key=%s AND payload_hash=%s",
                (message["sourceKey"], message["recordKey"], message["payloadHash"]),
            )
            row = cursor.fetchone()
        if row is None:
            raise ValueError("original source version missing")
        if isinstance(row["raw_payload"], (str, bytes)):
            row["raw_payload"] = json.loads(row["raw_payload"])
        return row


def connect_mysql() -> Any:
    """Connect using explicit environment or opt-in IAM DB auth and verified TLS.

    Environment passwords may be injected by Secrets Manager at runtime. The SDK
    uses the IAM/SSO credential chain; no AWS access keys are embedded or accepted.
    """
    try:
        import pymysql
    except ImportError as error:
        raise RuntimeError("install the optional aws dependency group") from error
    host = os.environ.get("PARLIAMENT_DB_HOST", "127.0.0.1")
    port = int(os.environ.get("PARLIAMENT_DB_PORT", "3307"))
    user = os.environ.get("PARLIAMENT_DB_USER")
    if not user:
        raise ValueError("PARLIAMENT_DB_USER required")
    password = os.environ.get("PARLIAMENT_DB_PASSWORD", "")
    options: dict[str, Any] = {}
    local = host in ("localhost", "127.0.0.1", "::1")
    if not local:
        ca = os.environ.get("PARLIAMENT_DB_TLS_CA")
        if not ca or not Path(ca).is_file():
            raise ValueError("verified DB TLS CA required for remote host")
        options.update(ssl_ca=ca, ssl_verify_cert=True, ssl_verify_identity=True)
    if os.environ.get("PARLIAMENT_DB_IAM") == "true":
        password = aws_client("rds").generate_db_auth_token(
            DBHostname=host, Port=port, DBUsername=user
        )
    return pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=os.environ.get("PARLIAMENT_DB_NAME", "parliament"),
        connect_timeout=10,
        read_timeout=15,
        write_timeout=15,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
        init_command="SET time_zone='+00:00'",
        **options,
    )
