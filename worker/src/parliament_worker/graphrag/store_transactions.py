"""Atomic private snapshots with optional thread-local result-wave batching."""

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import local
from urllib.parse import quote

from parliament_worker.graphrag.store_schema import SCHEMA
from parliament_worker.knowledge.files import (
    private_database_lock,
    private_database_sidecars_checked,
    private_database_size,
    private_read,
    private_write,
)

# sqlite3.deserialize() uses SQLite's 1 GiB default memdb ceiling. Switch to
# SQLite's durable file transactions before an active graph reaches that limit.
DISK_BACKED_AT_BYTES = 900_000_000
LOCK_WAIT_ATTEMPTS = 1200
SQLITE_BUSY_TIMEOUT_SECONDS = 60


@contextmanager
def _waiting_database_lock(database: Path, root: Path) -> Iterator[None]:
    """Wait up to a minute for an operator audit without retrying its body."""
    for attempt in range(LOCK_WAIT_ATTEMPTS + 1):
        guard = private_database_lock(database, root=root)
        try:
            guard.__enter__()
            break
        except ValueError as error:
            if str(error) != "pilot store busy" or attempt == LOCK_WAIT_ATTEMPTS:
                raise
            time.sleep(0.05)
    try:
        yield
    finally:
        guard.__exit__(None, None, None)


class BatchState:
    """Share one connection only within the coordinator's current thread."""

    def __init__(self) -> None:
        self._local = local()

    def current(self) -> sqlite3.Connection | None:
        """Return the current thread's open batch connection, if any."""
        return getattr(self._local, "connection", None)

    @contextmanager
    def bind(self, connection: sqlite3.Connection) -> Iterator[None]:
        """Attach one outer write transaction for a bounded result batch."""
        if self.current() is not None:
            raise ValueError("nested graph result batch")
        self._local.connection = connection
        self._local.counter = 0
        try:
            yield
        finally:
            del self._local.connection
            del self._local.counter

    @contextmanager
    def nested(self, *, write: bool) -> Iterator[sqlite3.Connection]:
        """Keep each nested store method atomic inside the shared snapshot."""
        connection = self.current()
        if connection is None:
            raise ValueError("graph result batch is not active")
        if not write:
            yield connection
            return
        self._local.counter += 1
        name = f"graph_batch_{self._local.counter}"
        connection.execute(f"SAVEPOINT {name}")
        try:
            yield connection
        except BaseException:
            connection.execute(f"ROLLBACK TO SAVEPOINT {name}")
            connection.execute(f"RELEASE SAVEPOINT {name}")
            raise
        else:
            connection.execute(f"RELEASE SAVEPOINT {name}")


@contextmanager
def database_transaction(
    root: Path,
    database: Path,
    *,
    write: bool,
    max_snapshot_bytes: int,
) -> Iterator[sqlite3.Connection]:
    """Use atomic snapshots for pilots and file transactions for large graphs."""
    if write:
        with _waiting_database_lock(database, root):
            if private_database_size(database, root=root) >= DISK_BACKED_AT_BYTES:
                with _disk_transaction(database, root, write=True) as connection:
                    yield connection
            else:
                snapshot = private_read(
                    database, root=root, max_bytes=max_snapshot_bytes
                )
                with _memory_transaction(
                    database, root, snapshot, max_snapshot_bytes
                ) as connection:
                    yield connection
        return
    if private_database_size(database, root=root) >= DISK_BACKED_AT_BYTES:
        with _waiting_database_lock(database, root):
            with _disk_transaction(database, root, write=False) as connection:
                yield connection
        return
    # Atomic replacement lets a reader keep one complete inode without the lock.
    snapshot = private_read(database, root=root, max_bytes=max_snapshot_bytes)
    connection = sqlite3.connect(":memory:")
    try:
        if snapshot:
            connection.deserialize(snapshot)
        connection.row_factory = sqlite3.Row
        connection.executescript(SCHEMA)
        yield connection
    finally:
        connection.close()


@contextmanager
def _memory_transaction(
    database: Path, root: Path, snapshot: bytes, max_snapshot_bytes: int
) -> Iterator[sqlite3.Connection]:
    """Commit a small in-memory revision using descriptor-relative replacement."""
    connection = sqlite3.connect(":memory:")
    try:
        if snapshot:
            connection.deserialize(snapshot)
        connection.row_factory = sqlite3.Row
        connection.executescript(SCHEMA)
        yield connection
        connection.commit()
        serialized = connection.serialize()
        if len(serialized) > max_snapshot_bytes:
            raise ValueError("graph database snapshot size exceeds limit")
        private_write(database, serialized, immutable=False, root=root)
    finally:
        connection.close()


@contextmanager
def _disk_transaction(
    database: Path, root: Path, *, write: bool
) -> Iterator[sqlite3.Connection]:
    """Commit directly to the checked private file using SQLite's journal."""
    private_database_sidecars_checked(database, root=root)
    if write:
        connection = sqlite3.connect(database, timeout=SQLITE_BUSY_TIMEOUT_SECONDS)
    else:
        uri = "file:" + quote(str(database), safe="/") + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=SQLITE_BUSY_TIMEOUT_SECONDS)
    try:
        connection.row_factory = sqlite3.Row
        if write:
            connection.executescript(SCHEMA)
            connection.execute("BEGIN IMMEDIATE")
        else:
            connection.execute("BEGIN")
        try:
            yield connection
            if write:
                connection.commit()
        except BaseException:
            connection.rollback()
            raise
    finally:
        connection.close()
