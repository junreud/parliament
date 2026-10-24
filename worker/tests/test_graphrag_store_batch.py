"""One result wave must not reload the whole private database per result."""

import pytest

from parliament_worker.graphrag import store_transactions
from parliament_worker.graphrag.store import GraphStore


def test_batch_shares_one_transaction_across_several_artifact_writes(
    tmp_path, monkeypatch
) -> None:
    """Independent store calls in one wave commit with one durable lock."""
    store = GraphStore(tmp_path / "state")
    original = store_transactions.private_database_lock
    opened = 0

    def counted(*args, **kwargs):
        nonlocal opened
        opened += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(store_transactions, "private_database_lock", counted)
    with store.batch():
        store.put_artifact("review", "first", {}, {"count": 1})
        store.put_artifact("review", "second", {}, {"count": 2})
        assert store.get_artifact("review", "first")["payload"] == {"count": 1}

    assert opened == 1
    reopened = GraphStore(tmp_path / "state")
    assert reopened.get_artifact("review", "first")["payload"] == {"count": 1}
    assert reopened.get_artifact("review", "second")["payload"] == {"count": 2}


def test_batch_rolls_back_one_caught_nested_write_without_losing_peers(
    tmp_path,
) -> None:
    """A failed result cannot leave half of its method's writes in the wave."""
    store = GraphStore(tmp_path / "state")
    with store.batch():
        store.put_artifact("review", "before", {}, {"ok": True})
        with pytest.raises(ValueError, match="synthetic validation error"):
            with store._transaction() as db:
                db.execute(
                    "INSERT INTO sources(scope,fingerprint,generation,payload,active) "
                    "VALUES('partial','hash',1,'{}',1)"
                )
                raise ValueError("synthetic validation error")
        store.put_artifact("review", "after", {}, {"ok": True})

    reopened = GraphStore(tmp_path / "state")
    with reopened._transaction(write=False) as db:
        assert (
            db.execute("SELECT COUNT(*) FROM sources WHERE scope='partial'").fetchone()[
                0
            ]
            == 0
        )
    assert reopened.get_artifact("review", "before") is not None
    assert reopened.get_artifact("review", "after") is not None


def test_batch_does_not_share_uncommitted_connection_with_other_thread(
    tmp_path,
) -> None:
    """The local operator API reads only committed data while a wave is open."""
    from concurrent.futures import ThreadPoolExecutor

    store = GraphStore(tmp_path / "state")
    with store.batch():
        store.put_artifact("review", "pending", {}, {"private": True})
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(store.get_artifact, "review", "pending").result() is None

    assert store.get_artifact("review", "pending") is not None
