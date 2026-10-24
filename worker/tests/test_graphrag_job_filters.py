"""Filtered job reads avoid decoding unrelated persisted requests."""

from pathlib import Path

from pytest import MonkeyPatch

from parliament_worker.graphrag import store as store_module
from parliament_worker.graphrag.store import GraphStore


def test_job_filters_decode_only_matching_rows(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Filtering by kind and state keeps order without loading other jobs."""
    store = GraphStore(tmp_path / "private")
    store.enqueue("extract", "first", {}, {})
    matching = store.enqueue("community", "second", {}, {})
    store.enqueue("community", "third", {}, {})
    store.update_job(matching, state="failed", error="test failure")

    original_loads = store_module.json.loads
    decoded: list[str] = []

    def recording_loads(value: str) -> object:
        decoded.append(value)
        return original_loads(value)

    monkeypatch.setattr(store_module.json, "loads", recording_loads)

    assert [job["id"] for job in store.jobs(kind="community", state="failed")] == [
        matching
    ]
    assert len(decoded) == 1

    decoded.clear()
    assert [job["id"] for job in store.jobs(state="failed")] == [matching]
    assert len(decoded) == 1
