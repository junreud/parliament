"""Publish and cloud adapters use fake clients; no AWS resources are touched."""

import hashlib
import json

import httpx
import pytest

from parliament_worker.aws import S3RawStore, SqsOutboxRelay, SqsVersionConsumer
from parliament_worker.publish import BackendPublisher


class FakeS3:
    def __init__(self):
        self.calls = []

    def put_object(self, **kwargs):
        self.calls.append(kwargs)
        return {"ETag": "fake"}


def test_s3_requires_opt_in_and_preserves_immutable_content_address():
    client = FakeS3()
    with pytest.raises(ValueError, match="opt-in"):
        S3RawStore("configured-bucket", client=client)
    store = S3RawStore("configured-bucket", client=client, enabled=True)
    key = store.save("korea", "9001", b"synthetic raw")
    assert hashlib.sha256(b"synthetic raw").hexdigest() in key
    assert client.calls[0]["IfNoneMatch"] == "*"
    assert client.calls[0]["ServerSideEncryption"] == "AES256"


class FakeOutbox:
    def __init__(self):
        self.sent = []
        self.failed = []

    def pending(self, limit):
        return [
            {
                "outbox_id": 7,
                "source_key": "assembly-bill",
                "record_key": "9001",
                "payload_hash": "a" * 64,
            }
        ]

    def mark_sent(self, outbox_id):
        self.sent.append(outbox_id)

    def mark_failed(self, outbox_id, error):
        self.failed.append((outbox_id, error))


class FakeSqs:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def send_message(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("private secret text")
        return {"MessageId": "message-1"}


def test_relay_sends_only_original_identity_version_and_marks_sent():
    outbox = FakeOutbox()
    sqs = FakeSqs()
    relay = SqsOutboxRelay(
        outbox,
        "https://sqs.ap-northeast-2.amazonaws.com/123456789012/parliament",
        client=sqs,
        enabled=True,
    )
    assert relay.run() == 1
    body = json.loads(sqs.calls[0]["MessageBody"])
    assert body == {
        "outboxId": 7,
        "sourceKey": "assembly-bill",
        "recordKey": "9001",
        "payloadHash": "a" * 64,
    }
    assert outbox.sent == [7]


def test_relay_failure_is_retryable_without_exposing_exception_text():
    outbox = FakeOutbox()
    relay = SqsOutboxRelay(
        outbox,
        "https://sqs.ap-northeast-2.amazonaws.com/123456789012/parliament",
        client=FakeSqs(fail=True),
        enabled=True,
    )
    assert relay.run() == 0
    assert outbox.failed == [(7, "RuntimeError")]


def test_publisher_posts_contract_and_never_follows_auth_redirect():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://evil.test/"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    publisher = BackendPublisher(
        "http://127.0.0.1:8080", "test-secret", enabled=True, client=client
    )
    with pytest.raises(ValueError, match="redirect"):
        publisher.publish({"id": "synthetic", "summary": None})
    assert len(requests) == 1
    assert requests[0].url.path == "/admin/tracking/events"
    assert requests[0].headers["X-Parliament-Ingestion-Key"] == "test-secret"


def test_publisher_rejects_unreviewed_summary_and_implicit_write():
    with pytest.raises(ValueError, match="opt-in"):
        BackendPublisher("http://127.0.0.1:8080", "test-secret")
    publisher = BackendPublisher("http://127.0.0.1:8080", "test-secret", enabled=True)
    with pytest.raises(ValueError, match="review"):
        publisher.publish({"summary": "generated unreviewed claim"})


def test_sqs_consumer_acknowledges_only_success_and_deduplicates(tmp_path):
    message = {
        "sourceKey": "assembly-bill",
        "recordKey": "9001",
        "payloadHash": "a" * 64,
        "outboxId": 7,
    }
    calls = []
    deleted = []

    class Client:
        def receive_message(self, **kwargs):
            return {
                "Messages": [
                    {"Body": json.dumps(message), "ReceiptHandle": "one"},
                    {"Body": json.dumps(message), "ReceiptHandle": "two"},
                ]
            }

        def delete_message(self, **kwargs):
            deleted.append(kwargs["ReceiptHandle"])

    consumer = SqsVersionConsumer(
        "https://sqs.ap-northeast-2.amazonaws.com/123456789012/parliament",
        tmp_path / "inbox.sqlite3",
        calls.append,
        client=Client(),
        enabled=True,
    )
    assert consumer.run_once() == 1
    assert len(calls) == 1 and deleted == ["one", "two"]
    consumer.close()


def test_backend_secret_redirect_is_refused_with_redirect_following_client():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "https://evil.test"})

    publisher = BackendPublisher(
        "http://127.0.0.1:8080",
        "test-secret",
        enabled=True,
        client=httpx.Client(
            transport=httpx.MockTransport(handler), follow_redirects=True
        ),
    )
    with pytest.raises(ValueError, match="redirect"):
        publisher.publish({"summary": None})
    assert len(requests) == 1
