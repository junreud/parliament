"""Concurrent results share bounded private storage snapshots."""

from test_graphrag_engine import SIGNATURE, drain, make_factory
from test_graphrag_inputs import fixture_batch

from parliament_worker.graphrag import store_transactions
from parliament_worker.graphrag.index import current_artifacts, graph_view
from parliament_worker.graphrag.inputs import sources_from_batch
from parliament_worker.graphrag.query import question_status, submit_question


def test_wave_lease_covers_batched_result_persistence(tmp_path, monkeypatch):
    factory, _ = make_factory(tmp_path)
    factory.plan()
    observed = []
    original = factory.store.claim

    def capture(owner, lease_seconds, limit=1, now=None):
        observed.append(lease_seconds)
        return original(owner, lease_seconds, limit=limit, now=now)

    monkeypatch.setattr(factory.store, "claim", capture)
    factory.tick(1)
    assert observed == [600]


def test_full_remote_graph_community_local_global_and_no_idle_regeneration(tmp_path):
    factory, _ = make_factory(tmp_path)
    drain(factory)
    store = factory.store
    assert len(graph_view(store)["edges"]) == 1
    assert len(current_artifacts(store, "community")) == 1
    local = submit_question(
        store, "김가는 어떤 법안을 대표발의했나?", "local", SIGNATURE
    )
    global_ = submit_question(store, "공식 기록의 주제는?", "global", SIGNATURE)
    drain(factory)
    assert question_status(store, local["id"])["state"] == "completed"
    global_answer = question_status(store, global_["id"])
    assert global_answer["state"] == "completed"
    assert global_answer["claims"][0]["evidence"]["documentVersion"] == "version-a"
    count = len(factory.client.accepted)
    drain(factory, cycles=3)
    assert len(factory.client.accepted) == count


def test_completed_result_wave_uses_one_store_transaction_per_bounded_batch(
    tmp_path, monkeypatch
):
    """Applying parallel completions does not reload the whole database per job."""
    factory, _ = make_factory(tmp_path)
    second = fixture_batch()
    second["documents"][0]["recordKey"] = "3"
    second["documents"][0]["id"] = "doc-b"
    second["evidence"][0]["documentId"] = "doc-b"
    factory.store.put_sources(sources_from_batch(second))
    factory.concurrency = 2
    factory.plan()
    assert len(factory.store.jobs(state="planned", kind="extract")) == 2
    factory.tick(2)
    for job in factory.store.jobs(state="polling", kind="extract"):
        factory.store.update_job(job["id"], next_poll=0)

    original = store_transactions.private_database_lock
    opened = 0

    def counted(*args, **kwargs):
        nonlocal opened
        opened += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(store_transactions, "private_database_lock", counted)
    factory.tick(2)
    assert len(factory.store.jobs(state="completed", kind="extract")) == 2
    assert opened <= 5
