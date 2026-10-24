"""Transactional mail claims with durable ambiguity states and user opt-out locks."""

import hashlib
import json
import logging
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from typing import Any

from parliament_worker.mail import (
    MailComposer,
    PreparedMail,
    PrivateSpool,
    SesMailer,
    token_link,
    utc_datetime,
)

LOGGER = logging.getLogger(__name__)


class MySqlMailOutbox:
    """Process queued Java messages; sending/sent/uncertain are never retried."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def pending(self, limit: int) -> list[dict[str, str]]:
        """Read a bounded queue snapshot; concurrent workers still recheck locks."""
        if not 1 <= limit <= 100:
            raise ValueError("invalid mail batch size")
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT mail_id,user_id FROM tracking_mail_outbox WHERE status='queued' ORDER BY created_at,mail_id LIMIT %s",
                (limit,),
            )
            return list(cursor.fetchall())

    def run(
        self,
        composer: MailComposer,
        spool: PrivateSpool,
        now: datetime,
        *,
        limit: int = 20,
        mailer: SesMailer | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> dict[str, int]:
        """Preview by default; explicit mailer performs one network attempt per claim.

        Preview keeps eligible rows queued. An invalid/expired message is cancelled
        in either mode. The caller must not expose MIME bytes or token payloads in
        logs, public artifacts, HTTP responses or backups without access controls.
        """
        counts: Counter[str] = Counter()
        current = clock if clock is not None else lambda: now
        for identity in self.pending(limit):
            result = self._prepare(
                identity, composer, spool, current, send=mailer is not None
            )
            if result == "sending":
                result = self._deliver(identity, composer, current, mailer)
            if result != "skipped":
                counts[result] += 1
        return dict(counts)

    def _locked(
        self, cursor: Any, identity: dict[str, str]
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """Lock user before mail, matching unsubscribe and digest generation order."""
        cursor.execute(
            "SELECT user_id,email,email_enabled,frequency,verified_at,unsubscribe_token FROM tracking_user WHERE user_id=%s FOR UPDATE",
            (identity["user_id"],),
        )
        user = cursor.fetchone()
        cursor.execute(
            "SELECT mail_id,user_id,mail_kind,payload,status,created_at FROM tracking_mail_outbox WHERE mail_id=%s AND user_id=%s FOR UPDATE",
            (identity["mail_id"], identity["user_id"]),
        )
        mail = cursor.fetchone()
        if mail and isinstance(mail["payload"], (str, bytes)):
            try:
                mail["payload"] = json.loads(mail["payload"])
            except (ValueError, UnicodeDecodeError):
                mail["payload"] = None
        return user, mail

    def _eligible(
        self,
        cursor: Any,
        user: dict[str, Any] | None,
        mail: dict[str, Any],
        now: datetime,
        base: str,
    ) -> bool:
        """Recheck current recipient preferences or unused login expiration."""
        payload = mail["payload"]
        if (
            not user
            or not isinstance(payload, dict)
            or payload.get("email") != user["email"]
            or mail["user_id"] != user["user_id"]
        ):
            return False
        try:
            if mail["mail_kind"] == "digest":
                token = token_link(payload.get("unsubscribeUrl"), base, "/unsubscribe")
                return bool(
                    user["email_enabled"]
                    and user["verified_at"] is not None
                    and user["frequency"] in ("daily", "weekly")
                    and payload.get("frequency") == user["frequency"]
                    and token == user["unsubscribe_token"]
                )
            if mail["mail_kind"] != "login":
                return False
            token = token_link(payload.get("loginUrl"), base, "/auth/verify")
            if utc_datetime(payload.get("expiresAt")) <= utc_datetime(now):
                return False
            cursor.execute(
                "SELECT user_id,expires_at,consumed_at FROM tracking_login_token WHERE token_hash=%s",
                (hashlib.sha256(token.encode()).hexdigest(),),
            )
            original = cursor.fetchone()
            return bool(
                original
                and original["user_id"] == user["user_id"]
                and original["consumed_at"] is None
                and utc_datetime(original["expires_at"]) > utc_datetime(now)
            )
        except (ValueError, TypeError, KeyError):
            return False

    @staticmethod
    def _status(cursor: Any, identity: dict[str, str], status: str) -> None:
        """Change only the already locked message using bound SQL parameters."""
        cursor.execute(
            "UPDATE tracking_mail_outbox SET status=%s WHERE mail_id=%s AND user_id=%s",
            (status, identity["mail_id"], identity["user_id"]),
        )

    def _prepare(
        self,
        identity: dict[str, str],
        composer: MailComposer,
        spool: PrivateSpool,
        clock: Callable[[], datetime],
        *,
        send: bool,
    ) -> str:
        """Validate under locks, then commit a durable sending claim before SES."""
        self.connection.begin()
        try:
            with self.connection.cursor() as cursor:
                user, mail = self._locked(cursor, identity)
                if not mail or mail["status"] != "queued":
                    result = "skipped"
                elif not self._eligible(cursor, user, mail, clock(), composer.base_url):
                    self._status(cursor, identity, "cancelled")
                    result = "cancelled"
                else:
                    try:
                        message = composer.compose(mail)
                    except (ValueError, KeyError, TypeError):
                        self._status(cursor, identity, "cancelled")
                        result = "cancelled"
                    else:
                        spool.write(message)
                        result = "sending" if send else "spooled"
                        if send:
                            self._status(cursor, identity, "sending")
            self.connection.commit()
            return result
        except Exception:
            self.connection.rollback()
            raise

    def _deliver(
        self,
        identity: dict[str, str],
        composer: MailComposer,
        clock: Callable[[], datetime],
        mailer: SesMailer,
    ) -> str:
        """Hold the user lock across one request; exceptions require reconciliation.

        Durable sending is intentionally separate from this transaction. A crash
        or an ambiguous commit therefore cannot roll the row back to queued and
        automatically resend. Pending queries never include stuck sending rows.
        """
        try:
            self.connection.begin()
            with self.connection.cursor() as cursor:
                user, mail = self._locked(cursor, identity)
                if not mail or mail["status"] != "sending":
                    result = "skipped"
                elif not self._eligible(cursor, user, mail, clock(), composer.base_url):
                    self._status(cursor, identity, "cancelled")
                    result = "cancelled"
                else:
                    message: PreparedMail = composer.compose(mail)
                    mailer.send(message)
                    self._status(cursor, identity, "sent")
                    result = "sent"
            self.connection.commit()
            return result
        except Exception as error:
            LOGGER.warning(
                "Mail outcome uncertain (%s); manual reconciliation required",
                type(error).__name__,
            )
            try:
                self.connection.rollback()
                self.connection.begin()
                with self.connection.cursor() as cursor:
                    _, mail = self._locked(cursor, identity)
                    if mail and mail["status"] == "sending":
                        self._status(cursor, identity, "uncertain")
                self.connection.commit()
            except Exception:
                LOGGER.error("Mail remains sending; manual reconciliation required")
                try:
                    self.connection.rollback()
                except Exception:
                    pass
            return "uncertain"
