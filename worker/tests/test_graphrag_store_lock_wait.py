"""Long operator reads must not exhaust the GraphRAG database lock retry."""

from pathlib import Path

from parliament_worker.graphrag import store_transactions


def test_database_lock_waits_beyond_old_five_second_limit(monkeypatch) -> None:
    """A bounded audit can occupy the lock for more than 101 short polls."""
    attempts = 0

    class Guard:
        def __enter__(self):
            nonlocal attempts
            attempts += 1
            if attempts <= 120:
                raise ValueError("pilot store busy")

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(
        store_transactions, "private_database_lock", lambda *_a, **_k: Guard()
    )
    monkeypatch.setattr(store_transactions.time, "sleep", lambda _seconds: None)

    with store_transactions._waiting_database_lock(Path("unused"), Path("unused")):
        pass
    assert attempts == 121
