"""Private pilot outputs refuse symlink traversal and preserve external files."""

import os
import sqlite3
from datetime import datetime, timezone

import pytest

from parliament_worker.knowledge.store import PilotStore, private_write

SPEC = {"id": "document-a", "sourceKey": "synthetic", "recordKey": "a"}
NOW = datetime(2024, 1, 1, tzinfo=timezone.utc)


def test_raw_parent_symlink_cannot_escape_store(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    store = PilotStore(tmp_path / "pilot")
    (store.root / "raw").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="path|symlink"):
        store.observe(SPEC, b"synthetic", "job-a", NOW)
    assert list(outside.iterdir()) == []
    store.close()


def test_extraction_parent_symlink_cannot_escape_store(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    store = PilotStore(tmp_path / "pilot")
    (store.root / "extractions").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="path|symlink"):
        store.save_extraction("document-a", {"extractionVersion": "extract_a"})
    assert list(outside.iterdir()) == []
    store.close()


def test_database_symlink_is_rejected_before_sqlite_mutation(tmp_path):
    outside = tmp_path / "outside.sqlite3"
    connection = sqlite3.connect(outside)
    connection.close()
    original = outside.read_bytes()
    directory = tmp_path / "pilot"
    directory.mkdir()
    (directory / "pilot.sqlite3").symlink_to(outside)
    with pytest.raises(ValueError, match="path|symlink"):
        PilotStore(directory)
    assert outside.read_bytes() == original


def test_export_target_symlink_does_not_overwrite_its_destination(tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"preserve")
    target = tmp_path / "export.json"
    target.symlink_to(outside)
    for immutable in (True, False):
        with pytest.raises(ValueError, match="path|symlink"):
            private_write(target, b"new", immutable=immutable)
    assert outside.read_bytes() == b"preserve"


def test_export_parent_symlink_is_rejected(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "export").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="path|symlink"):
        private_write(tmp_path / "export" / "file.json", b"new")
    assert list(outside.iterdir()) == []


def test_raw_read_refuses_swapped_symlink_even_with_equal_bytes(tmp_path):
    store = PilotStore(tmp_path / "pilot")
    observation = store.observe(SPEC, b"synthetic", "job-a", NOW)
    raw_path = store.root / observation["rawStorageKey"]
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"synthetic")
    raw_path.unlink()
    raw_path.symlink_to(outside)
    with pytest.raises(ValueError, match="path|symlink"):
        store.read_raw(observation)
    store.close()


def test_sqlite_connect_aba_swap_cannot_mutate_external_database(monkeypatch, tmp_path):
    outside = tmp_path / "outside.sqlite3"
    external = sqlite3.connect(outside)
    external.execute("CREATE TABLE sentinel(id INTEGER)")
    external.commit()
    external.close()
    directory = tmp_path / "pilot"
    directory.mkdir()
    database = directory / "pilot.sqlite3"
    database.write_bytes(b"")
    backup = directory / "original.sqlite3"
    real_connect = sqlite3.connect
    opened = []

    def swap_then_restore(path, *args, **kwargs):
        opened.append(str(path))
        database.rename(backup)
        database.symlink_to(outside)
        try:
            return real_connect(path, *args, **kwargs)
        finally:
            database.unlink()
            backup.rename(database)

    monkeypatch.setattr(sqlite3, "connect", swap_then_restore)
    store = PilotStore(directory)
    store.observe(SPEC, b"synthetic", "job-a", NOW)
    store.close()
    external = real_connect(outside)
    assert (
        external.execute(
            "SELECT name FROM sqlite_master WHERE name='observations'"
        ).fetchall()
        == []
    )
    external.close()
    assert opened == [":memory:"]


def test_memory_snapshot_is_restorable_and_serialized_under_exclusive_store_lock(
    tmp_path,
):
    directory = tmp_path / "pilot"
    first = PilotStore(directory)
    original = first.observe(SPEC, b"synthetic", "job-a", NOW)
    with pytest.raises(ValueError, match="busy"):
        PilotStore(directory)
    first.close()
    restored = PilotStore(directory)
    assert restored.observations(SPEC["id"])[0] == original
    assert restored.observe(SPEC, b"synthetic", "job-a", NOW) == original
    restored.close()


def test_immutable_partial_write_failure_never_publishes_a_broken_final(
    monkeypatch, tmp_path
):
    path = tmp_path / "raw.bin"
    fdopen = os.fdopen

    class PartialFailure:
        def __init__(self, descriptor, mode):
            self.handle = fdopen(descriptor, mode)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.handle.close()

        def write(self, value):
            self.handle.write(value[:3])
            self.handle.flush()
            raise OSError("synthetic disk failure")

    monkeypatch.setattr(
        os, "fdopen", lambda descriptor, mode: PartialFailure(descriptor, mode)
    )
    with pytest.raises(ValueError):
        private_write(path, b"synthetic original")
    assert not path.exists()
    assert list(tmp_path.iterdir()) == []
    monkeypatch.setattr(os, "fdopen", fdopen)
    private_write(path, b"synthetic original")
    private_write(path, b"synthetic original")
    assert path.read_bytes() == b"synthetic original"
