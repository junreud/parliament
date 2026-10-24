"""Storage regressions for incremental and uncertain remote GraphRAG work."""

import stat
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from parliament_worker.graphrag import store as store_module
from parliament_worker.graphrag import store_transactions
from parliament_worker.graphrag.store import GraphStore
from parliament_worker.graphrag.store_schema import MAX_SNAPSHOT_BYTES
from parliament_worker.knowledge.files import private_database_snapshot


def test_readers_use_atomic_snapshot_while_writer_owns_lock(tmp_path: Path) -> None:
    store = GraphStore(tmp_path / "private")
    store.put_source("official:one", "a", {"text": "original"})

    with private_database_snapshot(
        store.database, root=store.root, max_bytes=512_000_000
    ):
        assert store.sources()[0]["fingerprint"] == "a"
        assert store.status()["active_sources"] == 1


def test_graph_snapshot_accepts_bounded_hierarchy_capacity(tmp_path: Path) -> None:
    store = GraphStore(tmp_path / "private")
    assert MAX_SNAPSHOT_BYTES == 1_536_000_000
    with private_database_snapshot(
        store.database, root=store.root, max_bytes=MAX_SNAPSHOT_BYTES
    ) as snapshot:
        assert snapshot.startswith(b"SQLite format 3")
    with pytest.raises(ValueError, match="snapshot read limit"):
        with private_database_snapshot(
            store.database, root=store.root, max_bytes=MAX_SNAPSHOT_BYTES + 1
        ):
            pass


def test_source_recurrence_and_retirement_keep_generations(tmp_path: Path) -> None:
    store = GraphStore(tmp_path / "private")
    assert store.put_source("official:one", "a", {"text": "original"})
    assert not store.put_source("official:one", "a", {"text": "original"})
    assert store.put_source("official:one", "b", {"text": "corrected"})
    assert store.put_source("official:one", "a", {"text": "original"})
    assert store.source_current("official:one", "a", 3)
    assert not store.source_current("official:one", "a", 1)
    assert [row["generation"] for row in store.observations()] == [1, 2, 3]
    assert store.retire_source("official:one")
    assert not store.retire_source("official:one")
    assert not store.source_current("official:one", "a")
    assert store.sources() == []
    assert store.sources(active_only=False)[0]["generation"] == 4
    assert store.put_source("official:one", "a", {"text": "original"})
    assert store.sources()[0]["generation"] == 5
    assert [row["active"] for row in store.observations()] == [True] * 3 + [False, True]
    store.close()
    assert GraphStore(tmp_path / "private").observations() == store.observations()


def test_source_observation_time_tracks_current_revision_without_regression(
    tmp_path: Path,
) -> None:
    store = GraphStore(tmp_path / "private")
    source = {
        "scope": "official:one",
        "fingerprint": "a",
        "payload": {"text": "original"},
        "observedAt": "2026-10-16T12:00:00+00:00",
    }
    assert store.put_sources([source]) == 1
    assert store.source_observation_times() == {
        "official:one": "2026-10-16T12:00:00+00:00"
    }
    later = {**source, "observedAt": "2026-10-17T12:00:00+00:00"}
    assert store.record_source_observations([later]) == 1
    assert store.record_source_observations([source]) == 0
    assert store.sources()[0]["generation"] == 1
    assert GraphStore(tmp_path / "private").source_observation_times() == {
        "official:one": "2026-10-17T12:00:00+00:00"
    }
    with pytest.raises(ValueError, match="current source"):
        store.record_source_observations([{**later, "fingerprint": "wrong"}])

    assert (
        store.put_sources([{**later, "fingerprint": "b", "payload": {"text": "new"}}])
        == 1
    )
    assert store.source_observation_times() == {
        "official:one": "2026-10-17T12:00:00+00:00"
    }
    assert store.put_sources([later]) == 1
    assert store.sources()[0]["generation"] == 3
    assert store.source_observation_times() == {
        "official:one": "2026-10-17T12:00:00+00:00"
    }


def test_source_fingerprint_collision_does_not_change_snapshot(tmp_path: Path) -> None:
    store = GraphStore(tmp_path)
    store.put_source("doc", "version", {"text": "first"})
    original = store.database.read_bytes()
    with pytest.raises(ValueError, match="immutable source"):
        store.put_source("doc", "version", {"text": "second"})
    assert store.database.read_bytes() == original
    assert len(store.observations()) == 1


def test_uncertain_submission_restarts_with_identical_body_and_key(
    tmp_path: Path,
) -> None:
    store = GraphStore(tmp_path)
    request = {
        "model": "local-generator",
        "messages": [{"role": "user", "content": "공식 근거"}],
    }
    context = {"sources": [{"scope": "doc", "generation": 1}]}
    job_id = store.enqueue("relationships", "doc:1", request, context)
    store.update_job(job_id, state="submitting", attempts=1)
    restarted = GraphStore(tmp_path)
    assert restarted.enqueue("relationships", "doc:1", request, context) == job_id
    job = restarted.get_job(job_id)
    assert job and job["state"] == "submitting"
    assert job["request"] == request
    assert job["idempotency_key"] == "graphrag-" + job_id.removeprefix("gr_")
    assert len(restarted.pending()) == 1
    assert len(restarted.jobs()) == 1
    with pytest.raises(ValueError, match="replay conflict"):
        restarted.enqueue(
            "relationships", "doc:1", {**request, "temperature": 1}, context
        )
    assert restarted.get_job(job_id)["request"] == request


def test_job_completion_and_remote_identity_are_immutable(tmp_path: Path) -> None:
    store = GraphStore(tmp_path)
    job_id = store.enqueue("report", "one", {}, {})
    with pytest.raises(ValueError, match="invalid job transition"):
        store.update_job(job_id, state="completed", result={"answer": "too soon"})
    store.update_job(job_id, state="submitting")
    with pytest.raises(ValueError, match="requires remote"):
        store.update_job(job_id, state="polling")
    store.update_job(job_id, state="polling", remote_id="server-id")
    with pytest.raises(ValueError, match="remote request identity"):
        store.update_job(job_id, remote_id="replacement")
    store.update_job(job_id, state="completed", result={"answer": "근거"})
    with pytest.raises(ValueError, match="immutable"):
        store.update_job(job_id, result={"answer": "changed"})
    with pytest.raises(ValueError, match="immutable or unknown"):
        store.update_job(job_id, request={"changed": True})
    store.update_job(job_id, state="obsolete")
    assert store.get_job(job_id)["result"] == {"answer": "근거"}
    assert store.pending() == []


def test_claim_lease_cannot_be_stolen_and_expired_owner_cannot_commit(
    tmp_path: Path,
) -> None:
    store = GraphStore(tmp_path)
    job_id = store.enqueue("relationships", "one", {}, {})
    now = time.time()
    assert store.claim("worker-a", 60, now=now)[0]["id"] == job_id
    other = GraphStore(tmp_path)
    assert other.claim("worker-b", 60, now=now + 1) == []
    assert other.pending(now=now + 1) == []
    with pytest.raises(ValueError, match="active lease"):
        other.update_job(job_id, state="submitting")
    with pytest.raises(ValueError, match="stale"):
        other.release(job_id, "worker-b", now=now + 1, state="submitting")
    assert other.claim("worker-b", 60, now=now + 61)[0]["id"] == job_id
    with pytest.raises(ValueError, match="stale"):
        store.release(job_id, "worker-a", now=now + 61, state="submitting")
    other.release(job_id, "worker-b", now=now + 62, state="submitting", attempts=1)
    current = store.get_job(job_id)
    assert current["lease_owner"] is None
    assert current["state"] == "submitting"


def test_lease_renewal_preserves_owner_and_request(tmp_path: Path) -> None:
    store = GraphStore(tmp_path)
    job_id = store.enqueue("community", "one", {"model": "local-generator"}, {})
    assert store.claim("worker-a", 10, now=100)[0]["id"] == job_id
    original = store.get_job(job_id)
    with pytest.raises(ValueError, match="stale"):
        store.renew_leases("worker-b", [job_id], 10, now=105)
    store.renew_leases("worker-a", [job_id], 10, now=105)
    renewed = store.get_job(job_id)
    assert renewed["lease_owner"] == "worker-a"
    assert renewed["lease_until"] == 115
    assert renewed["request"] == original["request"]
    assert renewed["idempotency_key"] == original["idempotency_key"]
    with pytest.raises(ValueError, match="stale"):
        store.renew_leases("worker-a", [job_id], 10, now=116)


def test_deferred_due_work_and_invalid_limits(tmp_path: Path) -> None:
    store = GraphStore(tmp_path)
    first = store.enqueue("relationships", "one", {}, {})
    second = store.enqueue("report", "two", {}, {})
    store.update_job(first, state="deferred", next_poll=200)
    assert [job["id"] for job in store.pending(now=199)] == [second]
    assert [job["id"] for job in store.pending(now=200, limit=1)] == [first]
    with pytest.raises(ValueError, match="invalid job limit"):
        store.pending(limit=0)
    with pytest.raises(ValueError, match="invalid store clock"):
        store.pending(now=float("nan"))
    with pytest.raises(ValueError, match="invalid job state"):
        store.jobs(state="unrecognized")


def test_artifacts_preserve_invalidated_and_recurrent_versions(tmp_path: Path) -> None:
    store = GraphStore(tmp_path)
    one = store.put_artifact("community", "root", {"source": 1}, {"title": "A"})
    assert store.put_artifact("community", "root", {"source": 1}, {"title": "A"}) == one
    two = store.put_artifact("community", "root", {"source": 2}, {"title": "B"})
    assert one != two
    assert len(store.artifact_versions("community", "root")) == 2
    assert store.get_artifact("community", "root")["version"] == two
    assert len(store.artifacts("community")) == 1
    assert len(store.artifacts("community", current=False)) == 2
    store.invalidate_artifact("community", "root")
    assert store.get_artifact("community", "root") is None
    assert store.artifacts("community") == []
    assert len(store.artifact_versions("community", "root")) == 2
    assert store.put_artifact("community", "root", {"source": 1}, {"title": "A"}) == one
    assert store.get_artifact("community", "root")["version"] == one


def test_artifact_hash_collision_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = GraphStore(tmp_path)
    monkeypatch.setattr(store_module, "_digest", lambda value: "fixed")
    store.put_artifact("report", "root", "first", {"text": "first"})
    with pytest.raises(ValueError, match="immutable artifact"):
        store.put_artifact("report", "root", "changed", {"text": "second"})
    assert store.get_artifact("report", "root")["payload"] == {"text": "first"}


def test_concurrent_short_transactions_do_not_lose_other_writers(
    tmp_path: Path,
) -> None:
    first, second = GraphStore(tmp_path), GraphStore(tmp_path)

    def write_sources(store: GraphStore, prefix: str) -> None:
        for number in range(12):
            store.put_source(f"{prefix}:{number}", "revision", {"number": number})

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(write_sources, first, "a"),
            pool.submit(write_sources, second, "b"),
        ]
        for future in futures:
            future.result()
    restarted = GraphStore(tmp_path)
    assert len(restarted.sources()) == 24
    assert len(restarted.observations()) == 24


def test_credentials_never_enter_job_snapshots(tmp_path: Path) -> None:
    store = GraphStore(tmp_path)
    for request in (
        {"Authorization": "Bearer private"},
        {"extra": {"api_key": "private"}},
    ):
        with pytest.raises(ValueError, match="credentials must not"):
            store.enqueue("relationships", "one", request, {})
    assert b"Bearer private" not in store.database.read_bytes()
    assert store.jobs() == []


def test_private_permissions_and_symlink_boundaries(tmp_path: Path) -> None:
    root = tmp_path / "private"
    store = GraphStore(root)
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE(store.database.stat().st_mode) == 0o600
    target = tmp_path / "unrelated"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="unsafe private"):
        GraphStore(link / "nested")
    store.database.unlink()
    store.database.symlink_to(target / "untouched")
    with pytest.raises(ValueError, match="unsafe private"):
        GraphStore(root)
    assert not (target / "untouched").exists()
    with pytest.raises(ValueError, match="unsafe private"):
        GraphStore(tmp_path / ".." / "escaped")


def test_oversized_snapshot_fails_without_replacing_prior_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = GraphStore(tmp_path)
    previous = store.database.read_bytes()
    monkeypatch.setattr(store_module, "MAX_SNAPSHOT_BYTES", len(previous))
    with pytest.raises(ValueError, match="snapshot size exceeds"):
        store.put_source("one", "revision", {"text": "x" * len(previous)})
    assert store.database.read_bytes() == previous
    assert store.sources() == []
    assert store.status()["observations"] == 0


def test_disk_backed_store_grows_past_snapshot_limit_and_keeps_remote_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store_transactions, "DISK_BACKED_AT_BYTES", 0)
    store = GraphStore(tmp_path / "private")
    initial_size = store.database.stat().st_size
    monkeypatch.setattr(store_module, "MAX_SNAPSHOT_BYTES", initial_size)
    request = {
        "model": "local-generator",
        "messages": [{"role": "user", "content": "근거"}],
    }
    context = {"sources": [{"scope": "official:one", "generation": 1}]}
    store.put_source("official:one", "version-a", {"text": "x" * (initial_size * 2)})
    job_id = store.enqueue("extract", "official:one:segment", request, context)
    store.update_job(job_id, state="submitting", attempts=1)
    store.update_job(job_id, state="polling", remote_id="remote-request-1")

    reopened = GraphStore(tmp_path / "private")
    assert store.database.stat().st_size > initial_size
    assert reopened.sources()[0]["fingerprint"] == "version-a"
    assert (
        reopened.enqueue("extract", "official:one:segment", request, context) == job_id
    )
    assert reopened.get_job(job_id)["remote_id"] == "remote-request-1"


def test_disk_backed_store_refuses_journal_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store_transactions, "DISK_BACKED_AT_BYTES", 0)
    store = GraphStore(tmp_path / "private")
    outside = tmp_path / "outside"
    outside.write_text("untouched")
    journal = store.database.with_name(store.database.name + "-journal")
    journal.symlink_to(outside)

    with pytest.raises(ValueError, match="unsafe private"):
        store.put_source("official:one", "a", {"text": "evidence"})
    assert outside.read_text() == "untouched"
    journal.unlink()
    assert store.sources() == []


def test_disk_backed_batch_rolls_back_unfinished_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store_transactions, "DISK_BACKED_AT_BYTES", 0)
    store = GraphStore(tmp_path / "private")
    with pytest.raises(RuntimeError, match="unfinished"):
        with store.batch():
            store.put_source("official:one", "a", {"text": "first"})
            store.enqueue("extract", "first", {"messages": []}, {})
            raise RuntimeError("unfinished")

    reopened = GraphStore(tmp_path / "private")
    assert reopened.sources() == []
    assert reopened.jobs() == []
    assert reopened.status()["observations"] == 0


def test_status_distinguishes_old_failed_attempt_from_current_logical_success(
    tmp_path: Path,
) -> None:
    store = GraphStore(tmp_path)
    first = store.enqueue("extract", "attempt-one", {}, {"artifact_key": "person-a"})
    store.update_job(first, state="failed", error="generated_content_validation_failed")
    second = store.enqueue("extract", "attempt-two", {}, {"artifact_key": "person-a"})
    store.update_job(second, state="submitting")
    store.update_job(second, state="completed", result={"nodes": [], "edges": []})
    status = store.status()
    assert status["jobs"]["failed"] == 1
    assert status["latest_jobs"]["extract"]["completed"] == 1
    assert status["unresolved_failures"] == 0


def test_corpus_beyond_previous_64mb_ceiling_survives_reopen(tmp_path: Path) -> None:
    store = GraphStore(tmp_path)
    size = 32_100_000
    store.put_source("large", "revision", {"text": "x" * size})
    assert store.database.stat().st_size > 64_000_000
    reopened = GraphStore(tmp_path)
    source = reopened.sources()[0]
    assert source["fingerprint"] == "revision"
    assert len(source["payload"]["text"]) == size


def test_bulk_source_and_job_writes_are_atomic_and_replay_safe(tmp_path: Path) -> None:
    store = GraphStore(tmp_path)
    items = [
        {"scope": f"official:{index}", "fingerprint": "a", "payload": {"text": "A"}}
        for index in range(50)
    ]
    assert store.put_sources(items) == 50
    assert store.put_sources(items) == 0
    with pytest.raises(ValueError, match="immutable source"):
        store.put_sources(
            [
                {"scope": "new", "fingerprint": "b", "payload": {}},
                {
                    "scope": "official:0",
                    "fingerprint": "a",
                    "payload": {"text": "collision"},
                },
            ]
        )
    assert len(store.sources()) == 50
    jobs = [
        {
            "kind": "extract",
            "key": f"official:{index}",
            "request": {},
            "context": {"generation": 1},
        }
        for index in range(50)
    ]
    ids = store.enqueue_many(jobs)
    assert store.enqueue_many(jobs) == ids
    assert len(store.jobs()) == 50
    with pytest.raises(ValueError, match="replay conflict"):
        store.enqueue_many(
            [
                {"kind": "extract", "key": "new", "request": {}, "context": {}},
                {**jobs[0], "request": {"changed": True}},
            ]
        )
    assert len(store.jobs()) == 50


def test_query_work_has_priority_over_backfill_without_reordering_peers(
    tmp_path: Path,
) -> None:
    store = GraphStore(tmp_path)
    kinds = [
        "extract",
        "community",
        "query_map",
        "query_local",
        "query_reduce",
        "query_local",
    ]
    ids = store.enqueue_many(
        [
            {"kind": kind, "key": str(index), "request": {}, "context": {}}
            for index, kind in enumerate(kinds)
        ]
    )
    expected = [ids[index] for index in [3, 4, 5, 2, 0, 1]]
    assert [job["id"] for job in store.pending()] == expected
    assert [job["id"] for job in store.claim("worker", 60, limit=6)] == expected


def test_new_extraction_precedes_older_community_backlog(tmp_path: Path) -> None:
    """New source evidence must not wait behind a growing hierarchy queue."""
    store = GraphStore(tmp_path)
    communities = [
        store.enqueue("community", str(index), {}, {}) for index in range(64)
    ]
    extraction = store.enqueue("extract", "changed-source", {}, {})
    assert [job["id"] for job in store.claim("worker", 60, limit=1)] == [extraction]
    assert communities[0] != extraction


def test_pending_and_claim_do_not_decode_terminal_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Large completed results must not fill memory on every execution wave."""
    store = GraphStore(tmp_path)
    old = store.enqueue("query_map", "old", {}, {})
    current = store.enqueue("query_map", "current", {}, {})
    store.update_job(old, state="obsolete")
    original = store_module.json.loads

    def checked_loads(value, *args, **kwargs):
        if '"state":"obsolete"' in value:
            raise AssertionError("terminal history was decoded for runnable work")
        return original(value, *args, **kwargs)

    monkeypatch.setattr(store_module.json, "loads", checked_loads)
    assert [job["id"] for job in store.pending()] == [current]
    assert [job["id"] for job in store.claim("worker", 60)] == [current]


def test_failed_result_retry_precedes_fresh_community_backfill(tmp_path: Path) -> None:
    """Recovery should not wait behind newly planned hierarchy windows."""
    store = GraphStore(tmp_path)
    fresh = store.enqueue("community", "fresh", {}, {})
    retry = store.enqueue("community", "retry", {}, {"retry_of": "earlier-failed-job"})
    question = store.enqueue("query_local", "question", {}, {})
    assert [job["id"] for job in store.claim("worker", 60, limit=3)] == [
        question,
        retry,
        fresh,
    ]


def test_failed_query_map_retry_precedes_fresh_maps(tmp_path: Path) -> None:
    """One malformed map answer must not wait behind a global question backlog."""
    store = GraphStore(tmp_path)
    first = store.enqueue("query_map", "first", {}, {})
    second = store.enqueue("query_map", "second", {}, {})
    retry = store.enqueue("query_map", "retry", {}, {"retry_of": "failed-map"})
    assert [job["id"] for job in store.pending()] == [retry, first, second]


def test_evidence_bound_office_repair_precedes_fresh_community_backfill(
    tmp_path: Path,
) -> None:
    """A queued person-role repair must not starve behind hierarchy growth."""
    store = GraphStore(tmp_path)
    fresh = store.enqueue("community", "fresh", {}, {})
    repair = store.enqueue(
        "extract", "repair", {}, {"repair_version": "source-spaced-office-v1"}
    )
    question = store.enqueue("query_local", "question", {}, {})
    assert [job["id"] for job in store.claim("worker", 60, limit=3)] == [
        question,
        repair,
        fresh,
    ]


def test_untried_peer_is_claimed_before_another_retry_without_remote_id(
    tmp_path: Path,
) -> None:
    """A DNS-deferred request must not monopolize a repair wave."""
    store = GraphStore(tmp_path)
    first = store.enqueue(
        "extract", "first", {}, {"repair_version": "source-typed-list-office-v1"}
    )
    second = store.enqueue(
        "extract", "second", {}, {"repair_version": "source-typed-list-office-v1"}
    )
    store.update_job(first, state="deferred", attempts=1, next_poll=0)

    assert [job["id"] for job in store.claim("worker", 60, limit=2)] == [
        second,
        first,
    ]


def test_checkpoint_preserves_ownership_and_exact_request_after_restart(
    tmp_path: Path,
) -> None:
    store = GraphStore(tmp_path)
    request = {"messages": [{"role": "user", "content": "공식 문서"}]}
    job_id = store.enqueue("extract", "one", request, {})
    now = time.time()
    original = store.claim("worker-a", 120, now=now)[0]
    checkpoint = store.checkpoint(
        job_id,
        "worker-a",
        now=now + 1,
        state="submitting",
        attempts=1,
        metadata={"reserved": True},
    )
    assert checkpoint["lease_owner"] == original["lease_owner"]
    assert checkpoint["lease_until"] == original["lease_until"]
    assert checkpoint["request"] == request
    assert checkpoint["idempotency_key"] == original["idempotency_key"]
    restarted = GraphStore(tmp_path)
    assert restarted.get_job(job_id) == checkpoint
    assert restarted.claim("worker-b", 120, now=now + 2) == []
    restarted.release(
        job_id, "worker-a", now=now + 3, state="polling", remote_id="remote-id"
    )
    assert restarted.get_job(job_id)["remote_id"] == "remote-id"


def test_checkpoint_rejects_stale_owner_expiration_and_immutable_fields(
    tmp_path: Path,
) -> None:
    store = GraphStore(tmp_path)
    job_id = store.enqueue("extract", "one", {}, {})
    now = time.time()
    store.claim("worker-a", 120, now=now)
    with pytest.raises(ValueError, match="stale"):
        store.checkpoint(job_id, "worker-b", now=now + 1, state="submitting")
    with pytest.raises(ValueError, match="immutable or unknown"):
        store.checkpoint(job_id, "worker-a", now=now + 1, request={"different": True})
    with pytest.raises(ValueError, match="stale"):
        store.checkpoint(job_id, "worker-a", now=now + 120, state="submitting")
    assert store.get_job(job_id)["state"] == "planned"
    store.claim("worker-b", 120, now=now + 120)
    with pytest.raises(ValueError, match="stale"):
        store.checkpoint(job_id, "worker-a", now=now + 121, state="submitting")
    assert (
        store.checkpoint(job_id, "worker-b", now=now + 121, state="submitting")["state"]
        == "submitting"
    )


def test_remote_recovery_is_prioritized_before_new_query_work(tmp_path: Path) -> None:
    store = GraphStore(tmp_path)
    kinds = ["extract", "query_local", "community", "extract"]
    ids = store.enqueue_many(
        [
            {"kind": kind, "key": str(index), "request": {}, "context": {}}
            for index, kind in enumerate(kinds)
        ]
    )
    store.update_job(ids[0], state="submitting")
    store.update_job(ids[2], state="submitting")
    store.update_job(ids[2], state="polling", remote_id="remote-id")
    assert [job["id"] for job in store.pending()] == [ids[2], ids[0], ids[1], ids[3]]
    assert [job["id"] for job in store.claim("worker", 60, limit=4)] == [
        ids[2],
        ids[0],
        ids[1],
        ids[3],
    ]
