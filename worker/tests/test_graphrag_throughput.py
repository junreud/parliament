"""Keep planning and validation independent of repeated full-snapshot loading."""

import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from test_graphrag_concurrency import configured_factory
from test_graphrag_engine import SIGNATURE, RemoteFixture, drain, make_factory

from parliament_worker.graphrag.client import InferenceError
from parliament_worker.graphrag.engine import Factory
from parliament_worker.graphrag.index import plan_communities, reconcile
from parliament_worker.graphrag.store import GraphStore


def test_planning_uses_one_community_read_instead_of_per_leaf_lookups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory, _ = make_factory(tmp_path)
    drain(factory)
    reads = []
    original = factory.store.get_artifact

    def traced_read(kind, key):
        reads.append((kind, key))
        return original(kind, key)

    monkeypatch.setattr(factory.store, "get_artifact", traced_read)
    factory.plan()
    assert not [item for item in reads if item[0] == "community"]


def test_community_planning_reuses_job_and_report_snapshots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A growing retained history should be decoded once per plan pass."""
    factory, _ = make_factory(tmp_path)
    drain(factory)
    store = factory.store
    counts = {"jobs": 0, "community": 0}
    jobs = store.jobs
    artifacts = store.artifacts

    def counted_jobs(*args, **kwargs):
        counts["jobs"] += 1
        return jobs(*args, **kwargs)

    def counted_artifacts(kind):
        if kind == "community":
            counts["community"] += 1
        return artifacts(kind)

    monkeypatch.setattr(store, "jobs", counted_jobs)
    monkeypatch.setattr(store, "artifacts", counted_artifacts)
    assert plan_communities(store, SIGNATURE) == 0
    assert counts == {"jobs": 1, "community": 1}


def test_full_request_backlog_skips_unneeded_graph_planners(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Preplanned maps must not repeatedly scan every graph and source."""
    factory, _ = make_factory(tmp_path)
    factory.queue_capacity = 1
    assert factory.plan()["extractions"] == 1
    reduction_calls = []

    def unexpected(*_args, **_kwargs):
        raise AssertionError("graph planner ran with a full request backlog")

    monkeypatch.setattr(
        "parliament_worker.graphrag.factory_plan.plan_question_reductions",
        lambda _store: reduction_calls.append(True) or 0,
    )
    for name in (
        "plan_office_repairs",
        "plan_lineage_repairs",
        "plan_policy_links",
        "plan_activity_links",
        "plan_communities",
        "plan_extractions",
        "plan_claim_repairs",
    ):
        monkeypatch.setattr(
            f"parliament_worker.graphrag.factory_plan.{name}", unexpected
        )

    result = factory.plan()
    assert result["reductions"] == 0
    assert result["extractions"] == 0
    assert reduction_calls == [True]


def test_source_metadata_omits_body_and_preserves_recurrence_and_retirement(
    tmp_path: Path,
) -> None:
    store = GraphStore(tmp_path)
    store.put_source("doc", "a", {"text": "large source"})
    store.put_source("doc", "b", {"text": "correction"})
    store.put_source("doc", "a", {"text": "large source"})
    assert store.sources(include_payload=False) == [
        {"scope": "doc", "fingerprint": "a", "generation": 3, "active": True}
    ]
    assert store.sources()[0]["payload"] == {"text": "large source"}
    store.retire_source("doc")
    assert store.sources(include_payload=False) == []
    assert store.sources(active_only=False, include_payload=False) == [
        {"scope": "doc", "fingerprint": "a", "generation": 4, "active": False}
    ]


def test_completed_result_checks_only_source_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory, _ = make_factory(tmp_path)
    factory.plan()
    factory.tick(1)
    job = factory.store.jobs()[0]
    factory.store.update_job(job["id"], next_poll=0)
    original = factory.store.sources
    full_reads = []

    def checked_sources(*args, **kwargs):
        if kwargs.get("include_payload", True):
            full_reads.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(factory.store, "sources", checked_sources)
    factory.tick(1)
    assert factory.store.get_job(job["id"])["state"] == "completed"
    assert full_reads == []
    assert factory.store.artifacts("graph")[0]["payload"]["edges"]


def test_reconciliation_does_not_reload_snapshot_for_each_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory, _ = make_factory(tmp_path)
    drain(factory)
    reads = []
    original = factory.store.get_artifact

    def traced_read(kind, key):
        reads.append((kind, key))
        return original(kind, key)

    monkeypatch.setattr(factory.store, "get_artifact", traced_read)
    assert reconcile(factory.store) == 0
    assert reads == []


def test_reconciliation_withdraws_descendants_in_same_pass(tmp_path: Path) -> None:
    factory, _ = make_factory(tmp_path)
    drain(factory)
    graph = factory.store.artifacts("graph")[0]
    parent = factory.store.artifacts("community")[0]
    factory.store.put_artifact(
        "graph",
        graph["key"],
        graph["dependency"],
        {**graph["payload"], "changed": True},
    )
    assert reconcile(factory.store) >= 1
    assert factory.store.get_artifact("community", parent["key"]) is None


def test_reconciliation_retires_many_descendants_in_one_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory, _ = make_factory(tmp_path)
    drain(factory)
    store = factory.store
    graph = store.artifacts("graph")[0]
    parent = store.artifacts("community")[0]
    for number in range(4):
        store.put_artifact(
            "community", f"stale-{number}", parent["dependency"], parent["payload"]
        )
    store.put_artifact(
        "graph",
        graph["key"],
        graph["dependency"],
        {**graph["payload"], "changed": True},
    )
    writes = 0
    original = store._transaction

    @contextmanager
    def traced(*, write=True):
        nonlocal writes
        with original(write=write) as db:
            if write:
                writes += 1
            yield db

    monkeypatch.setattr(store, "_transaction", traced)
    assert reconcile(store) >= 5
    assert writes == 1
    assert all(store.get_artifact("community", f"stale-{n}") is None for n in range(4))
    assert reconcile(store) == 0
    assert writes == 1


def test_community_planning_retires_stale_reports_in_one_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory, _ = make_factory(tmp_path)
    drain(factory)
    store = factory.store
    report = store.artifacts("community")[0]
    for number in range(4):
        store.put_artifact(
            "community",
            f"leaf:retired:{number}",
            report["dependency"],
            report["payload"],
        )
    writes = 0
    original = store._transaction

    @contextmanager
    def traced(*, write=True):
        nonlocal writes
        with original(write=write) as db:
            if write:
                writes += 1
            yield db

    monkeypatch.setattr(store, "_transaction", traced)
    assert plan_communities(store, SIGNATURE) == 0
    assert writes == 1
    assert all(
        store.get_artifact("community", f"leaf:retired:{n}") is None for n in range(4)
    )


def test_all_receipts_in_wave_use_one_snapshot_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote = RemoteFixture()
    factory = configured_factory(tmp_path, remote, 32, concurrency=32)
    writes = 0
    before_http = []
    original_transaction = factory.store._transaction
    original_submit = remote.submit

    @contextmanager
    def traced_transaction(*, write=True):
        nonlocal writes
        with original_transaction(write=write) as connection:
            if write:
                writes += 1
            yield connection

    def submitted(body, key):
        before_http.append(writes)
        return original_submit(body, key)

    monkeypatch.setattr(factory.store, "_transaction", traced_transaction)
    monkeypatch.setattr(remote, "submit", submitted)
    assert factory.tick(32) == 32
    assert writes - min(before_http) == 1
    assert len(factory.store.jobs(state="polling")) == 32


def test_dns_failures_in_wave_share_one_snapshot_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote = RemoteFixture()
    factory = configured_factory(tmp_path, remote, 32, concurrency=32)
    assert factory.tick(32) == 32
    original_ids = {
        job["id"]: job["remote_id"] for job in factory.store.jobs(state="polling")
    }
    for job_id in original_ids:
        factory.store.update_job(job_id, next_poll=0)

    def dns_unavailable(_remote_id):
        raise InferenceError("inference_dns_unavailable", retryable=True)

    monkeypatch.setattr(remote, "poll", dns_unavailable)
    writes = 0
    original_transaction = factory.store._transaction

    @contextmanager
    def traced_transaction(*, write=True):
        nonlocal writes
        with original_transaction(write=write) as connection:
            if write:
                writes += 1
            yield connection

    monkeypatch.setattr(factory.store, "_transaction", traced_transaction)
    assert factory.tick(32) == 0
    assert writes <= 4
    deferred = factory.store.jobs(state="deferred")
    assert len(deferred) == 32
    assert {job["id"]: job["remote_id"] for job in deferred} == original_ids
    assert len(remote.submissions) == 32


def test_completed_receipt_is_durable_before_validation_and_resumes_by_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from parliament_worker.graphrag.execution import WAVE_LEASE_SECONDS

    remote = RemoteFixture()
    factory = configured_factory(tmp_path, remote, 1, concurrency=4)
    original_submit = remote.submit

    def completed_submission(body, key):
        receipt = original_submit(body, key)
        return {**remote.poll(key), "request_id": receipt["request_id"]}

    def stopped_before_validation(job, response, now):
        stored = factory.store.get_job(job["id"])
        assert stored["remote_id"] == response["request_id"]
        assert stored["metadata"]["completion_uncertain"] is False
        raise RuntimeError("validation interrupted")

    monkeypatch.setattr(remote, "submit", completed_submission)
    monkeypatch.setattr(factory, "_complete", stopped_before_validation)
    with pytest.raises(RuntimeError, match="validation interrupted"):
        factory.tick(1)
    recovered = factory.store.claim(
        "recovery", 120, now=time.time() + WAVE_LEASE_SECONDS + 1
    )
    assert len(recovered) == 1
    factory.store.release(recovered[0]["id"], "recovery", next_poll=0)
    restarted = Factory(factory.store, remote, SIGNATURE, concurrency=4)
    assert restarted.tick(1) == 1
    assert factory.store.jobs()[0]["state"] == "completed"
    assert len(remote.submissions) == 1
