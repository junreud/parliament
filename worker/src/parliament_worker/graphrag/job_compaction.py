"""Create a verified private copy with losslessly packed GraphRAG job history."""

import hashlib
import os
import sqlite3
import stat
from pathlib import Path
from urllib.parse import quote

from parliament_worker.graphrag.job_codec import decode_job, encode_job
from parliament_worker.graphrag.store_schema import canonical_json

TABLE_ORDER = {
    "sources": "scope",
    "source_versions": "scope,fingerprint",
    "observations": "sequence",
    "source_observation_times": "scope,fingerprint,generation",
    "jobs": "rowid",
    "artifacts": "sequence",
}


def _semantic_digest(db: sqlite3.Connection) -> str:
    """Hash all versioned content and the insertion order of durable jobs."""
    digest = hashlib.sha256()
    for table, ordering in TABLE_ORDER.items():
        digest.update(table.encode("ascii"))
        for row in db.execute(f"SELECT * FROM {table} ORDER BY {ordering}"):
            value = list(row)
            if table == "jobs":
                value[3] = decode_job(value[3])
            digest.update(canonical_json(value).encode("utf-8"))
            digest.update(b"\n")
    return digest.hexdigest()


def copy_packed_jobs(source: Path, target: Path) -> dict[str, int | str]:
    """Back up a graph DB, pack copied jobs, and verify every logical row.

    Args:
        source: Existing private GraphRAG SQLite database, left untouched.
        target: New path in a private directory; it must not exist.

    Returns:
        Original/copy sizes, job count, and semantic digest for audit.

    Raises:
        ValueError: Unsafe paths, invalid source, or non-equivalent copy.
    """
    if (
        source.is_symlink()
        or not source.is_file()
        or target.exists()
        or target.is_symlink()
        or target.parent.is_symlink()
        or not target.parent.is_dir()
        or stat.S_IMODE(source.stat().st_mode) & 0o077
        or stat.S_IMODE(target.parent.stat().st_mode) & 0o077
        or source.absolute() == target.absolute()
    ):
        raise ValueError("unsafe graph job compaction path")
    original_bytes = source.stat().st_size
    descriptor = os.open(
        target, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o600
    )
    os.close(descriptor)
    origin: sqlite3.Connection | None = None
    copy: sqlite3.Connection | None = None
    failed = False
    try:
        origin = sqlite3.connect(
            "file:" + quote(str(source.absolute()), safe="/") + "?mode=ro", uri=True
        )
        copy = sqlite3.connect(target)
        origin.backup(copy)
        if copy.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("source backup failed SQLite integrity check")
        before = _semantic_digest(copy)
        count = 0
        last_rowid = 0
        while True:
            rows = copy.execute(
                "SELECT rowid,data FROM jobs WHERE rowid>? ORDER BY rowid LIMIT 500",
                (last_rowid,),
            ).fetchall()
            if not rows:
                break
            with copy:
                for rowid, data in rows:
                    copy.execute(
                        "UPDATE jobs SET data=? WHERE rowid=?",
                        (encode_job(decode_job(data)), rowid),
                    )
                    count += 1
            last_rowid = rows[-1][0]
        copy.execute("VACUUM")
        if copy.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("packed copy failed SQLite integrity check")
        after = _semantic_digest(copy)
        if before != after:
            raise ValueError("packed copy changed graph history")
        os.chmod(target, 0o600, follow_symlinks=False)
        return {
            "sourceBytes": original_bytes,
            "packedBytes": target.stat().st_size,
            "jobCount": count,
            "semanticSha256": after,
        }
    except BaseException:
        failed = True
        raise
    finally:
        if copy is not None:
            copy.close()
        if origin is not None:
            origin.close()
        if failed:
            target.unlink(missing_ok=True)
