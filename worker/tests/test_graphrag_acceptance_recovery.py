"""Uncertain acceptance is recovered only with the original request identity."""

from parliament_worker.graphrag.recovery import (
    drain_unknown_acceptance,
    recover_unknown_acceptance,
)
from parliament_worker.graphrag.store import GraphStore

SIGNATURE = "repo@example-revision"


class Remote:
    def __init__(self, *, revision="example-revision"):
        self.revision = revision
        self.calls = []

    def ready(self):
        return {
            "ready": True,
            "model_repository": "repo",
            "model_revision": self.revision,
        }

    def submit(self, body, key):
        self.calls.append((body, key))
        return {"request_id": "existing-id", "state": "queued"}


def make_uncertain(tmp_path):
    store = GraphStore(tmp_path / "state")
    body = {"model": "local-generator", "messages": [{"role": "user", "content": "x"}]}
    job_id = store.enqueue("extract", "test-key", body, {"model_signature": SIGNATURE})
    store.update_job(
        job_id,
        state="deferred",
        error="inference_transport_unavailable",
        metadata={"completion_uncertain": True, "expected_model": SIGNATURE},
    )
    store.put_artifact(
        "control",
        "pause",
        {},
        {"reason": "inference_acceptance_unknown", "jobId": job_id},
    )
    return store, store.get_job(job_id)


def test_recovery_uses_same_body_and_key_and_resumes_polling(tmp_path):
    store, job = make_uncertain(tmp_path)
    remote = Remote()
    assert recover_unknown_acceptance(store, remote, SIGNATURE)
    assert remote.calls == [(job["request"], job["idempotency_key"])]
    recovered = store.get_job(job["id"])
    assert recovered["remote_id"] == "existing-id"
    assert recovered["state"] == "polling"
    assert not recovered["metadata"]["completion_uncertain"]
    assert store.get_artifact("control", "pause") is None
    assert not recover_unknown_acceptance(store, remote, SIGNATURE)


def test_recovery_waits_for_exact_model_revision(tmp_path):
    store, job = make_uncertain(tmp_path)
    remote = Remote(revision="different")
    assert not recover_unknown_acceptance(store, remote, SIGNATURE)
    assert remote.calls == []
    assert store.get_job(job["id"]) == job
    assert store.get_artifact("control", "pause") is not None


def test_unexpected_ready_fields_leave_original_pending(tmp_path):
    store, job = make_uncertain(tmp_path)
    remote = Remote()
    remote.ready = lambda: {
        "ready": True,
        "model_repository": None,
        "model_revision": "example-revision",
    }
    assert not recover_unknown_acceptance(store, remote, SIGNATURE)
    assert remote.calls == []
    assert store.get_job(job["id"]) == job


def test_recovery_drains_all_uncertain_jobs_after_pause_key_is_overwritten(tmp_path):
    """A 502 wave must not lose earlier unknown acceptances behind one pause key."""
    store, first = make_uncertain(tmp_path)
    second_id = store.enqueue(
        "extract", "second-key", first["request"], {"model_signature": SIGNATURE}
    )
    store.update_job(
        second_id,
        state="deferred",
        error="inference_http_error",
        metadata={"completion_uncertain": True, "expected_model": SIGNATURE},
    )
    store.put_artifact(
        "control",
        "pause",
        {},
        {"reason": "inference_acceptance_unknown", "jobId": second_id},
    )
    remote = Remote()

    assert recover_unknown_acceptance(store, remote, SIGNATURE)
    assert store.get_artifact("control", "pause")["payload"]["jobId"] == first["id"]
    assert recover_unknown_acceptance(store, remote, SIGNATURE)
    assert store.get_artifact("control", "pause") is None
    assert remote.calls == [
        (
            store.get_job(second_id)["request"],
            store.get_job(second_id)["idempotency_key"],
        ),
        (first["request"], first["idempotency_key"]),
    ]


def test_recovery_finds_uncertain_job_even_when_pause_artifact_is_missing(tmp_path):
    """Startup reconciliation recovers an accepted request whose pause was lost."""
    store, job = make_uncertain(tmp_path)
    store.invalidate_artifact("control", "pause")
    remote = Remote()

    assert recover_unknown_acceptance(store, remote, SIGNATURE)
    assert remote.calls == [(job["request"], job["idempotency_key"])]
    assert store.get_job(job["id"])["state"] == "polling"


def test_drain_recovers_backlog_before_expensive_graph_planning(tmp_path):
    """One operator pass recovers all persisted unknown requests, up to its bound."""
    store, first = make_uncertain(tmp_path)
    second_id = store.enqueue(
        "extract", "second-key", first["request"], {"model_signature": SIGNATURE}
    )
    store.update_job(
        second_id,
        state="deferred",
        error="inference_http_error",
        metadata={"completion_uncertain": True, "expected_model": SIGNATURE},
    )
    remote = Remote()

    assert drain_unknown_acceptance(store, remote, SIGNATURE, limit=2) == 2
    assert len(remote.calls) == 2
    assert store.get_artifact("control", "pause") is None
    assert all(
        store.get_job(job_id)["state"] == "polling"
        for job_id in (first["id"], second_id)
    )
