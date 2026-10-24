"""A retry is unresolved until its newest attempt actually completes."""

import json

from parliament_worker.graphrag.store import GraphStore


def test_failed_logical_key_stays_pending_until_retry_succeeds(tmp_path):
    store = GraphStore(tmp_path / "state")
    first = store.enqueue_many(
        [
            {
                "kind": "community",
                "key": "first",
                "request": {"model": "test"},
                "context": {"artifact_key": "parent:1:0"},
            }
        ]
    )[0]
    store.update_job(first, state="failed", error="generated_content_validation_failed")
    retry = store.enqueue_many(
        [
            {
                "kind": "community",
                "key": "retry",
                "request": {"model": "test"},
                "context": {"artifact_key": "parent:1:0", "retry_of": first},
            }
        ]
    )[0]

    waiting = store.status()
    assert waiting["unresolved_failures"] == 0
    assert waiting["failed_keys_pending_recovery"] == 1

    store.update_job(retry, state="submitting")
    store.update_job(retry, state="completed", result={"groups": []})
    assert store.status()["failed_keys_pending_recovery"] == 0


def test_status_does_not_decode_stored_requests_or_results(tmp_path, monkeypatch):
    """Operational counts must stay bounded as historical results accumulate."""
    store = GraphStore(tmp_path / "state")
    store.enqueue("query_map", "first", {"messages": ["large body"]}, {})

    def unexpected(*_args, **_kwargs):
        raise AssertionError("status decoded a full job payload")

    monkeypatch.setattr(json, "loads", unexpected)
    status = store.status()
    assert status["jobs"]["planned"] == 1
