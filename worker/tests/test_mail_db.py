"""Synthetic DB-API transactions exercise mail lifecycle without network."""

import copy
from datetime import timedelta

import pytest
from test_mail import BASE, TOKEN, composer, row

from parliament_worker.mail import PrivateSpool, SesMailer
from parliament_worker.mail_db import MySqlMailOutbox


class FakeConnection:
    """Model transaction commits and row-lock ordering for one synthetic user."""

    def __init__(self, now, kind="digest"):
        self.mail = row(now, kind)
        self.user = {
            "user_id": self.mail["user_id"],
            "email": self.mail["payload"]["email"],
            "email_enabled": True,
            "verified_at": now,
            "frequency": "weekly",
            "unsubscribe_token": TOKEN,
        }
        self.token = {
            "user_id": self.mail["user_id"],
            "expires_at": now + timedelta(minutes=15),
            "consumed_at": None,
        }
        self.operations = []
        self.commits = []
        self.after_commit = None

    def begin(self):
        self.operations.append("begin")
        self.snapshot = copy.deepcopy((self.mail, self.user))

    def commit(self):
        self.operations.append("commit")
        self.commits.append(self.mail["status"])
        if self.after_commit:
            callback = self.after_commit
            self.after_commit = None
            callback()

    def rollback(self):
        self.operations.append("rollback")
        if hasattr(self, "snapshot"):
            self.mail, self.user = self.snapshot

    def cursor(self):
        return FakeCursor(self)


class FakeCursor:
    """Return synthetic rows and record SQL lock/state order."""

    def __init__(self, db):
        self.db = db
        self.result = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, query, params=()):
        db = self.db
        if query.startswith("SELECT mail_id,user_id FROM"):
            self.result = (
                [{"mail_id": db.mail["mail_id"], "user_id": db.mail["user_id"]}]
                if db.mail["status"] == "queued"
                else []
            )
        elif "FROM tracking_user" in query:
            assert "FOR UPDATE" in query
            db.operations.append("lock_user")
            self.result = copy.deepcopy(db.user)
        elif "FROM tracking_mail_outbox" in query:
            assert "FOR UPDATE" in query and db.operations[-1] == "lock_user"
            db.operations.append("lock_mail")
            self.result = copy.deepcopy(db.mail)
        elif "FROM tracking_login_token" in query:
            self.result = copy.deepcopy(db.token)
        elif query.startswith("UPDATE tracking_mail_outbox"):
            db.mail["status"] = params[0]
            db.operations.append("status_" + params[0])
        else:
            raise AssertionError("unexpected SQL")

    def fetchone(self):
        return self.result

    def fetchall(self):
        return self.result


def test_default_spool_does_not_claim_or_deliver_and_is_idempotent(tmp_path, now):
    db = FakeConnection(now)
    repository = MySqlMailOutbox(db)
    spool = PrivateSpool(tmp_path / "mail")
    assert repository.run(composer(), spool, now) == {"spooled": 1}
    assert db.mail["status"] == "queued"
    assert repository.run(composer(), spool, now) == {"spooled": 1}
    assert len(list(spool.root.glob("*.eml"))) == 1
    assert "status_sending" not in db.operations


@pytest.mark.parametrize("change", ["unsubscribe", "frequency", "email", "unverified"])
def test_current_digest_settings_are_rechecked_under_user_lock(tmp_path, now, change):
    db = FakeConnection(now)
    if change == "unsubscribe":
        db.user["email_enabled"] = False
    elif change == "frequency":
        db.user["frequency"] = "daily"
    elif change == "email":
        db.user["email"] = "other@example.invalid"
    else:
        db.user["verified_at"] = None
    result = MySqlMailOutbox(db).run(composer(), PrivateSpool(tmp_path), now)
    assert result == {"cancelled": 1} and db.mail["status"] == "cancelled"
    assert not list(tmp_path.glob("*.eml"))


@pytest.mark.parametrize("change", ["expired", "used", "payload_expired"])
def test_login_checks_both_database_and_payload_expiry(tmp_path, now, change):
    db = FakeConnection(now, "login")
    if change == "expired":
        db.token["expires_at"] = now - timedelta(seconds=1)
    elif change == "used":
        db.token["consumed_at"] = now
    else:
        db.mail["payload"]["expiresAt"] = (now - timedelta(seconds=1)).isoformat()
    assert MySqlMailOutbox(db).run(composer(), PrivateSpool(tmp_path), now) == {
        "cancelled": 1
    }


def test_sending_is_committed_before_one_ses_call_and_sent_is_terminal(tmp_path, now):
    db = FakeConnection(now)
    calls = []

    class FakeSes:
        def send_email(self, **kwargs):
            assert db.mail["status"] == "sending"
            assert db.commits == ["sending"]
            assert db.operations[-1] == "lock_mail"
            calls.append(kwargs)
            return {"MessageId": "synthetic"}

    repository = MySqlMailOutbox(db)
    mailer = SesMailer(client=FakeSes(), enabled=True)
    assert repository.run(composer(), PrivateSpool(tmp_path), now, mailer=mailer) == {
        "sent": 1
    }
    assert db.commits == ["sending", "sent"]
    assert repository.run(composer(), PrivateSpool(tmp_path), now, mailer=mailer) == {}
    assert len(calls) == 1


def test_unsubscribe_between_claim_and_network_cancels_delivery(tmp_path, now):
    db = FakeConnection(now)
    db.after_commit = lambda: db.user.update(email_enabled=False, frequency="off")

    class NeverSend:
        def send(self, message):
            pytest.fail("unsubscribed mail must not reach SES")

    assert MySqlMailOutbox(db).run(
        composer(), PrivateSpool(tmp_path), now, mailer=NeverSend()
    ) == {"cancelled": 1}
    assert db.commits == ["sending", "cancelled"]


def test_ambiguous_delivery_is_uncertain_and_never_automatically_retried(tmp_path, now):
    db = FakeConnection(now)
    calls = []

    class Ambiguous:
        def send(self, message):
            calls.append(message.mail_id)
            raise TimeoutError("synthetic timeout with private content")

    repository = MySqlMailOutbox(db)
    spool = PrivateSpool(tmp_path)
    assert repository.run(composer(), spool, now, mailer=Ambiguous()) == {
        "uncertain": 1
    }
    assert db.mail["status"] == "uncertain"
    assert repository.run(composer(), spool, now, mailer=Ambiguous()) == {}
    assert len(calls) == 1


def test_stuck_sending_and_cancelled_rows_are_never_claimed(tmp_path, now):
    db = FakeConnection(now)
    repository = MySqlMailOutbox(db)
    for state in ("sending", "uncertain", "cancelled", "sent"):
        db.mail["status"] = state
        assert repository.run(composer(), PrivateSpool(tmp_path), now) == {}


def test_replaced_unsubscribe_token_cancels_old_digest(tmp_path, now):
    db = FakeConnection(now)
    db.mail["payload"]["unsubscribeUrl"] = BASE + "/unsubscribe?token=" + "x" * 43
    assert MySqlMailOutbox(db).run(composer(), PrivateSpool(tmp_path), now) == {
        "cancelled": 1
    }


def test_login_expiration_is_rechecked_after_waiting_for_user_lock(tmp_path, now):
    db = FakeConnection(now, "login")
    checks = iter([now, now + timedelta(minutes=16)])

    class NeverSend:
        def send(self, message):
            pytest.fail("expired login must not reach SES")

    assert MySqlMailOutbox(db).run(
        composer(),
        PrivateSpool(tmp_path),
        now,
        mailer=NeverSend(),
        clock=lambda: next(checks),
    ) == {"cancelled": 1}


def test_malformed_json_is_cancelled_without_delivery(tmp_path, now):
    db = FakeConnection(now)
    db.mail["payload"] = "not JSON"
    assert MySqlMailOutbox(db).run(composer(), PrivateSpool(tmp_path), now) == {
        "cancelled": 1
    }
