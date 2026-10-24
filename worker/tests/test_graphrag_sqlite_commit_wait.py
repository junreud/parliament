"""Regression for a disk-backed graph commit during a concurrent audit read."""

import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from parliament_worker.graphrag import store_transactions
from parliament_worker.graphrag.store import GraphStore


def test_disk_commit_waits_for_long_read_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A six-second operator read must not terminate the factory writer."""
    monkeypatch.setattr(store_transactions, "DISK_BACKED_AT_BYTES", 0)
    store = GraphStore(tmp_path / "private")
    store.put_source("official:one", "first", {"text": "initial"})
    reader = sqlite3.connect(store.database)
    reader.execute("BEGIN")
    reader.execute("SELECT count(*) FROM sources").fetchone()
    started = Event()

    def write_source() -> bool:
        started.set()
        return store.put_source("official:two", "second", {"text": "new"})

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(write_source)
            assert started.wait(timeout=2)
            time.sleep(6)
            reader.rollback()
            assert future.result(timeout=5)
    finally:
        reader.close()

    assert {source["scope"] for source in store.sources()} == {
        "official:one",
        "official:two",
    }
