"""Synthetic mail payloads; no real email addresses, AWS calls or delivery."""

import stat
from datetime import timedelta
from email import policy
from email.parser import BytesParser

import pytest

from parliament_worker.mail import MailComposer, PrivateSpool, SesMailer

MAIL_ID = "00000000-0000-4000-8000-000000000001"
USER_ID = "00000000-0000-4000-8000-000000000002"
TOKEN = "t" * 43
BASE = "https://synthetic.example"


def row(now, kind="digest"):
    """Return a synthetic Java-compatible queue row."""
    payload = {
        "email": "reader@example.invalid",
        "frequency": "weekly",
        "activities": [
            {
                "id": "event_1",
                "version": "a" * 64,
                "title": "[합성] 법안 변경",
                "corrected": True,
                "url": BASE + "/activities/event_1",
            }
        ],
        "unsubscribeUrl": BASE + "/unsubscribe?token=" + TOKEN,
        "coverage": "[합성] 검수된 공개 활동",
    }
    if kind == "login":
        payload = {
            "email": "reader@example.invalid",
            "loginUrl": BASE + "/auth/verify?token=" + TOKEN,
            "expiresAt": (now + timedelta(minutes=15)).isoformat(),
        }
    return {
        "mail_id": MAIL_ID,
        "user_id": USER_ID,
        "mail_kind": kind,
        "payload": payload,
        "status": "queued",
        "created_at": now,
    }


def composer():
    """Configure only synthetic sender/origin values."""
    return MailComposer("service@example.invalid", BASE)


def test_digest_links_pin_original_version_and_stable_message_id(now):
    message = composer().compose(row(now))
    parsed = BytesParser(policy=policy.default).parsebytes(message.raw)
    body = parsed.get_body(preferencelist=("plain",)).get_content()
    assert "/activities/event_1?version=" + "a" * 64 in body
    assert "[정정]" in body and "/unsubscribe?token=" + TOKEN in body
    assert str(parsed["Message-ID"]) == f"<{MAIL_ID}@synthetic.example>"
    assert message == composer().compose(row(now))


def test_private_spool_is_private_immutable_and_idempotent(tmp_path, now):
    target = tmp_path / "spool"
    message = composer().compose(row(now))
    spool = PrivateSpool(target)
    path = spool.write(message)
    assert stat.S_IMODE(target.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert spool.write(message) == path and len(list(target.iterdir())) == 1
    changed = row(now)
    changed["payload"]["activities"][0]["title"] = "[합성] 다른 내용"
    with pytest.raises(ValueError, match="conflict"):
        spool.write(composer().compose(changed))


def test_spool_rejects_symlink_root(tmp_path):
    target = tmp_path / "link"
    target.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        PrivateSpool(target)


@pytest.mark.parametrize("field", ["email", "unsubscribeUrl"])
def test_injected_headers_or_external_token_links_are_rejected(field, now):
    queued = row(now)
    queued["payload"][field] = (
        "reader@example.invalid\r\nBcc: attacker@example.invalid"
        if field == "email"
        else "https://attacker.example/unsubscribe?token=" + TOKEN
    )
    with pytest.raises(ValueError):
        composer().compose(queued)


@pytest.mark.parametrize("punctuation", list(".!#$%&'*+/=?^_`{|}~-"))
def test_backend_ascii_email_local_characters_are_deliverable(punctuation, now):
    queued = row(now)
    address = "reader" + punctuation + "policy@example.invalid"
    queued["payload"]["email"] = address
    message = composer().compose(queued)
    parsed = BytesParser(policy=policy.default).parsebytes(message.raw)
    assert parsed["To"].addresses[0].addr_spec == address


def test_mail_address_matches_backend_normalization_and_local_length(now):
    from parliament_worker.mail import email_address

    assert (
        email_address(" Reader+Policy@Example.Invalid ")
        == "reader+policy@example.invalid"
    )
    assert email_address("a" * 64 + "@example.invalid")
    with pytest.raises(ValueError):
        email_address("a" * 65 + "@example.invalid")


def test_login_link_is_same_origin_exact_path_and_token(now):
    queued = row(now, "login")
    message = composer().compose(queued)
    parsed = BytesParser(policy=policy.default).parsebytes(message.raw)
    assert TOKEN in parsed.get_body(preferencelist=("plain",)).get_content()
    queued["payload"]["loginUrl"] = BASE + "/other?token=" + TOKEN
    with pytest.raises(ValueError):
        composer().compose(queued)


def test_mail_token_link_rejects_control_characters(now):
    queued = row(now)
    queued["payload"]["unsubscribeUrl"] = BASE + "/unsubscribe?\ntoken=" + TOKEN
    with pytest.raises(ValueError, match="token"):
        composer().compose(queued)


def test_ses_adapter_requires_opt_in_and_sends_once_with_stable_tag(now):
    calls = []

    class FakeSes:
        def send_email(self, **kwargs):
            calls.append(kwargs)
            return {"MessageId": "synthetic-message"}

    with pytest.raises(ValueError, match="opt-in"):
        SesMailer(client=FakeSes())
    adapter = SesMailer(client=FakeSes(), enabled=True)
    message = composer().compose(row(now))
    assert adapter.send(message) == "synthetic-message"
    assert calls == [
        {
            "FromEmailAddress": message.sender,
            "Destination": {"ToAddresses": [message.recipient]},
            "Content": {"Raw": {"Data": message.raw}},
            "EmailTags": [{"Name": "parliament_mail_id", "Value": MAIL_ID}],
        }
    ]


def test_ses_sdk_retries_are_disabled(monkeypatch):
    import sys
    from types import SimpleNamespace

    captured = {}

    def client(service, **kwargs):
        captured.update(service=service, **kwargs)
        return object()

    class FakeConfig:
        def __init__(self, **kwargs):
            self.options = kwargs

    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=client))
    monkeypatch.setitem(
        sys.modules, "botocore.config", SimpleNamespace(Config=FakeConfig)
    )
    SesMailer(enabled=True)
    assert captured["service"] == "sesv2"
    assert captured["config"].options["retries"]["total_max_attempts"] == 1
    assert captured["region_name"] == "ap-northeast-2"
