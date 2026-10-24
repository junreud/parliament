"""Private mail previews and explicitly enabled SES delivery without retries."""

import os
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import UUID


def email_address(value: Any) -> str:
    """Match Java's canonical ASCII address contract without header controls."""
    if not isinstance(value, str) or any(ord(char) < 32 for char in value):
        raise ValueError("invalid mail address")
    value = value.strip().lower()
    if len(value) > 254 or not re.fullmatch(
        r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}",
        value,
    ):
        raise ValueError("invalid mail address")
    return value


def public_base(value: str) -> str:
    """Accept a fixed HTTPS web origin or an explicit loopback development origin."""
    parsed = urlsplit(value)
    local = parsed.hostname in ("localhost", "127.0.0.1", "::1")
    if (
        not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or any(ord(char) < 33 for char in value)
        or (parsed.scheme != "https" and not (local and parsed.scheme == "http"))
    ):
        raise ValueError("invalid public mail link origin")
    return value.rstrip("/")


def token_link(value: Any, base: str, path: str) -> str:
    """Require one unambiguous same-origin token link with an exact allowed path."""
    if (
        not isinstance(value, str)
        or len(value) > 2048
        or any(ord(char) < 33 for char in value)
    ):
        raise ValueError("invalid mail token link")
    parsed = urlsplit(value)
    origin = urlsplit(base)
    query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
    if (
        parsed.scheme != origin.scheme
        or parsed.netloc != origin.netloc
        or parsed.path != path
        or parsed.fragment
        or set(query) != {"token"}
        or len(query["token"]) != 1
        or not re.fullmatch(r"[A-Za-z0-9_-]{43}", query["token"][0])
    ):
        raise ValueError("invalid mail token link")
    return query["token"][0]


def utc_datetime(value: Any) -> datetime:
    """Normalize database UTC timestamps and ISO timestamps for expiration checks."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime):
        raise ValueError("invalid mail timestamp")
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass(frozen=True)
class PreparedMail:
    """Validated deterministic MIME envelope; raw bytes contain private tokens."""

    mail_id: str
    sender: str
    recipient: str
    raw: bytes


class MailComposer:
    """Render login/digest messages using only validated fixed-origin links."""

    def __init__(self, sender: str, base_url: str) -> None:
        self.sender = email_address(sender)
        self.base_url = public_base(base_url)

    def compose(self, row: dict[str, Any]) -> PreparedMail:
        """Build a stable plain-text message from one Java outbox payload."""
        mail_id = row["mail_id"]
        if not isinstance(mail_id, str) or str(UUID(mail_id)) != mail_id:
            raise ValueError("invalid mail identity")
        payload = row["payload"]
        if not isinstance(payload, dict):
            raise ValueError("invalid mail payload")
        recipient = email_address(payload.get("email"))
        if row["mail_kind"] == "login":
            token_link(payload.get("loginUrl"), self.base_url, "/auth/verify")
            utc_datetime(payload.get("expiresAt"))
            subject = "국회 활동 서비스 로그인"
            body = "로그인하려면 아래 링크를 여세요.\n\n" + payload["loginUrl"]
            body += "\n\n링크는 한 번만 사용할 수 있고 유효 시간이 지나면 만료됩니다.\n"
        elif row["mail_kind"] == "digest":
            subject = "관심 있는 국회 활동의 변경 사항"
            body = self._digest(payload)
        else:
            raise ValueError("unsupported mail kind")
        message = EmailMessage(policy=SMTP)
        message["From"] = self.sender
        message["To"] = recipient
        message["Subject"] = subject
        message["Date"] = format_datetime(utc_datetime(row["created_at"]))
        message["Message-ID"] = f"<{mail_id}@{urlsplit(self.base_url).hostname}>"
        message.set_content(body)
        raw = message.as_bytes()
        if len(raw) > 1_000_000:
            raise ValueError("mail exceeds byte limit")
        return PreparedMail(mail_id, self.sender, recipient, raw)

    def _digest(self, payload: dict[str, Any]) -> str:
        """Render reviewed cards with exact version pins and an unsubscribe link."""
        token_link(payload.get("unsubscribeUrl"), self.base_url, "/unsubscribe")
        if payload.get("frequency") not in ("daily", "weekly"):
            raise ValueError("invalid digest frequency")
        activities = payload.get("activities")
        if not isinstance(activities, list) or not 1 <= len(activities) <= 100:
            raise ValueError("invalid digest activity count")
        lines = ["관심 설정에 맞는 검수된 공개 활동입니다.", ""]
        for item in activities:
            if not isinstance(item, dict):
                raise ValueError("invalid digest activity")
            for key in ("id", "version"):
                if not isinstance(item.get(key), str) or not re.fullmatch(
                    r"[A-Za-z0-9_-]{1,128}", item[key]
                ):
                    raise ValueError("invalid digest version identity")
            title = item.get("title")
            if (
                not isinstance(title, str)
                or not 1 <= len(title) <= 500
                or any(ord(char) < 32 for char in title)
                or not isinstance(item.get("corrected"), bool)
            ):
                raise ValueError("invalid digest title")
            prefix = "[정정] " if item["corrected"] else ""
            link = self.base_url + "/activities/" + item["id"]
            link += "?" + urlencode({"version": item["version"]})
            lines.extend([prefix + title, link, ""])
        lines.extend(["알림 해지: " + payload["unsubscribeUrl"], ""])
        return "\n".join(lines)


class PrivateSpool:
    """Store sensitive MIME previews in a private directory without queue delivery."""

    def __init__(self, root: Path) -> None:
        if root.is_symlink():
            raise ValueError("mail spool root cannot be a symlink")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        root.chmod(0o700)
        self.root = root

    def write(self, message: PreparedMail) -> Path:
        """Atomically link an immutable mode-600 preview keyed by stable mail ID."""
        if str(UUID(message.mail_id)) != message.mail_id:
            raise ValueError("invalid mail identity")
        path = self.root / (message.mail_id + ".eml")
        descriptor, name = tempfile.mkstemp(prefix=".mail-", dir=self.root)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(message.raw)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                if path.is_symlink() or path.read_bytes() != message.raw:
                    raise ValueError("immutable mail spool conflict") from None
                path.chmod(0o600)
        finally:
            temporary.unlink(missing_ok=True)
        return path


class SesMailer:
    """Send once via SESv2 IAM chain; outcome reconciliation belongs to operators."""

    def __init__(self, *, client: Any = None, enabled: bool = False) -> None:
        if not enabled:
            raise ValueError("SES delivery requires explicit opt-in")
        self.client = client if client is not None else self._client()

    @staticmethod
    def _client() -> Any:
        """Disable SDK retries because SES does not accept an idempotency key."""
        try:
            import boto3
            from botocore.config import Config
        except ImportError as error:
            raise RuntimeError("install the optional aws dependency group") from error
        return boto3.client(
            "sesv2",
            region_name="ap-northeast-2",
            config=Config(
                retries={"total_max_attempts": 1, "mode": "standard"},
                connect_timeout=10,
                read_timeout=20,
            ),
        )

    def send(self, message: PreparedMail) -> str:
        """Make exactly one request, tagging the stable ID for manual reconciliation."""
        response = self.client.send_email(
            FromEmailAddress=message.sender,
            Destination={"ToAddresses": [message.recipient]},
            Content={"Raw": {"Data": message.raw}},
            EmailTags=[{"Name": "parliament_mail_id", "Value": message.mail_id}],
        )
        message_id = response.get("MessageId")
        if not isinstance(message_id, str) or not message_id:
            raise ValueError("ambiguous SES response")
        return message_id
