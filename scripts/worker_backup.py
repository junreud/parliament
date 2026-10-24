"""Private worker snapshots and isolated restores; external upload is explicit."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import sqlite3
import stat
import subprocess
import tarfile
import tempfile
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

LOGGER = logging.getLogger(__name__)
SQLITE_NAMES = frozenset(
    {"review.sqlite3", "raw-index.sqlite3", "inbox.sqlite3", "pilot.sqlite3"}
)
HASH = re.compile(r"[a-f0-9]{64}")
MAX_FILES = 100000
MAX_FILE_BYTES = 1024**3
MAX_TOTAL_BYTES = 16 * 1024**3
CHUNK = 1024 * 1024


def manifest_path(snapshot: Path) -> Path:
    """Return the external checksum/member manifest for one tar.gz snapshot."""
    return snapshot.with_suffix(".json")


def private_write(path: Path, content: bytes) -> None:
    """Create an owner-only artifact without overwriting an existing file."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def digest(path: Path) -> str:
    """Hash regular bytes with bounded memory, refusing a final symlink."""
    value = hashlib.sha256()
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("regular snapshot file required")
        while chunk := stream.read(CHUNK):
            value.update(chunk)
    return value.hexdigest()


def persistent(name: str) -> bool:
    """Allow only known state layouts, never credentials, mail or arbitrary files."""
    path = PurePosixPath(name)
    if (
        not name
        or len(name) > 1024
        or path.is_absolute()
        or "\\" in name
        or any(ord(char) < 32 for char in name)
        or any(
            part in ("", ".", "..") or part.startswith(".") for part in name.split("/")
        )
        or any(
            re.search(r"credential|secret|password|token|private-key", part, re.I)
            for part in path.parts
        )
    ):
        return False
    if path.name in SQLITE_NAMES or path.name == "report.json":
        return True
    if "summary_drafts" in path.parts:
        return bool(re.fullmatch(r"(?:request_)?[a-f0-9]{64}\.json", path.name))
    if "extractions" in path.parts:
        return bool(re.fullmatch(r"extract_[a-f0-9]{64}\.json", path.name))
    if "knowledge-batches" in path.parts:
        return bool(
            re.fullmatch(
                r"(?:batch|roster_batch)_[a-f0-9]{64}(?:\.(?:receipt|review-guide))?\.json",
                path.name,
            )
        )
    if "runs" in path.parts:
        return bool(re.fullmatch(r"[A-Za-z0-9_-]{1,128}\.json", path.name))
    if "raw" in path.parts or "processed" in path.parts:
        return bool(
            re.fullmatch(r"(?:[a-f0-9]{40}|[a-f0-9]{64})\.(?:json|bin)", path.name)
        )
    return False


def _directory(path: Path, *, create: bool = False) -> Path:
    """Resolve an explicitly configured root; internal/root symlinks are refused."""
    if path.is_symlink():
        raise ValueError("snapshot root cannot be a symlink")
    if create:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.chmod(0o700)
    if not path.is_dir():
        raise ValueError("snapshot directory required")
    return path.resolve()


def _files(root: Path) -> list[Path]:
    """Walk private state without following links and select a bounded allowlist."""
    found = []
    for current, directories, files in os.walk(root, followlinks=False):
        parent = Path(current)
        for name in directories + files:
            if (parent / name).is_symlink():
                raise ValueError("worker state contains a symlink")
        directories[:] = [
            name
            for name in directories
            if not name.startswith(".")
            and not re.search(r"credential|secret|password", name, re.I)
        ]
        for name in files:
            path = parent / name
            if not persistent(path.relative_to(root).as_posix()):
                continue
            if not stat.S_ISREG(path.stat(follow_symlinks=False).st_mode):
                raise ValueError("regular worker state file required")
            found.append(path)
            if len(found) > MAX_FILES:
                raise ValueError("worker snapshot file count exceeds limit")
    return sorted(found)


def _sqlite_integrity(path: Path) -> None:
    """Verify a standalone SQLite database without creating or modifying it."""
    try:
        with closing(
            sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)
        ) as connection:
            if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError("sqlite integrity verification failed")
    except sqlite3.Error as error:
        raise ValueError("sqlite integrity verification failed") from error


def _sqlite_snapshot(source: Path, target: Path) -> None:
    """Use SQLite backup API, including committed WAL state, not raw WAL copying."""
    if source.is_symlink():
        raise ValueError("sqlite source cannot be a symlink")
    started = time.monotonic()

    def progress(status: int, remaining: int, total: int) -> None:
        """Bound busy retries and active-writer snapshot time."""
        if time.monotonic() - started > 30:
            raise TimeoutError("sqlite backup deadline exceeded")

    try:
        with closing(
            sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=1)
        ) as original:
            with closing(sqlite3.connect(target)) as saved:
                original.backup(saved, pages=128, progress=progress, sleep=0.01)
                saved.execute("PRAGMA journal_mode=DELETE")
    except sqlite3.Error as error:
        raise ValueError("sqlite backup failed") from error
    target.chmod(0o600)
    _sqlite_integrity(target)


def _copy(source: Path, target: Path) -> None:
    """Copy only a regular file with O_NOFOLLOW and a bounded byte count."""
    descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as original:
        if not stat.S_ISREG(os.fstat(original.fileno()).st_mode):
            raise ValueError("regular worker state file required")
        output = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(output, "wb") as saved:
            size = 0
            while chunk := original.read(CHUNK):
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    raise ValueError("worker state file exceeds byte limit")
                saved.write(chunk)


def command(arguments: list[str]) -> None:
    """Run an explicit IAM/awscli upload without exposing output or credentials."""
    try:
        subprocess.run(
            arguments,
            check=True,
            timeout=180,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as error:
        raise RuntimeError("private worker backup upload failed") from error


def backup(
    source: Path,
    directory: Path,
    *,
    upload: bool = False,
    s3_prefix: str | None = None,
) -> Path:
    """Preserve private state; optional upload failures retain the valid local copy.

    Args:
        source: Worker data root protected by the operator's shared worker lock.
        directory: Separate private local recovery directory.
        upload: Explicit opt-in for external AWS CLI requests.
        s3_prefix: Existing private bucket's backups/ prefix; no ACL changes.

    Returns:
        Owner-only tar.gz snapshot with an external member/checksum manifest.
    """
    if upload != bool(s3_prefix) or (
        s3_prefix
        and not re.fullmatch(
            r"s3://[a-z0-9.-]+/backups(?:/[A-Za-z0-9/_-]+)?", s3_prefix
        )
    ):
        raise ValueError("upload requires explicit private S3 backups prefix")
    root = _directory(source)
    if directory.resolve().is_relative_to(root):
        raise ValueError("backup directory must be outside worker state")
    destination = _directory(directory, create=True)
    paths = _files(root)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    snapshot = destination / f"worker-{stamp}-{secrets.token_hex(4)}.tar.gz"
    manifest = manifest_path(snapshot)
    owned_snapshot = owned_manifest = False
    try:
        with tempfile.TemporaryDirectory(
            prefix=".worker-backup-", dir=destination
        ) as temporary:
            stage = Path(temporary)
            entries: dict[str, dict[str, Any]] = {}
            total = 0
            for path in paths:
                relative = path.relative_to(root).as_posix()
                saved = stage / relative
                saved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                kind = "sqlite" if path.name in SQLITE_NAMES else "file"
                (_sqlite_snapshot if kind == "sqlite" else _copy)(path, saved)
                size = saved.stat().st_size
                total += size
                if size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                    raise ValueError("worker snapshot byte limit exceeded")
                entries[relative] = {
                    "size": size,
                    "sha256": digest(saved),
                    "kind": kind,
                }
            descriptor = os.open(snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            owned_snapshot = True
            with os.fdopen(descriptor, "wb") as output:
                with tarfile.open(fileobj=output, mode="w:gz") as archive:
                    for name, metadata in entries.items():
                        item = tarfile.TarInfo(name)
                        item.mode = 0o600
                        item.size = metadata["size"]
                        with (stage / name).open("rb") as saved:
                            archive.addfile(item, saved)
                output.flush()
                os.fsync(output.fileno())
            private_write(
                manifest,
                json.dumps(
                    {
                        "format": 1,
                        "createdAt": stamp,
                        "sha256": digest(snapshot),
                        "files": entries,
                    },
                    sort_keys=True,
                    indent=2,
                ).encode(),
            )
            owned_manifest = True
    except BaseException:
        if owned_snapshot:
            snapshot.unlink(missing_ok=True)
        if owned_manifest:
            manifest.unlink(missing_ok=True)
        raise
    if upload:
        for item in (snapshot, manifest):
            command(
                [
                    "aws",
                    "s3",
                    "cp",
                    str(item),
                    f"{s3_prefix.rstrip('/')}/{item.name}",
                    "--sse",
                    "AES256",
                    "--region",
                    "ap-northeast-2",
                    "--only-show-errors",
                ]
            )
    LOGGER.info(
        "Worker snapshot complete: %s files; private local artifacts retained",
        len(entries),
    )
    return snapshot


def _manifest(snapshot: Path) -> dict[str, dict[str, Any]]:
    """Verify archive checksum and bounded allowlisted member metadata."""
    path = manifest_path(snapshot)
    if path.is_symlink() or path.stat().st_size > 32 * 1024**2:
        raise ValueError("invalid worker snapshot manifest")
    value = json.loads(path.read_bytes())
    if (
        not isinstance(value, dict)
        or value.get("format") != 1
        or digest(snapshot) != value.get("sha256")
    ):
        raise ValueError("worker snapshot checksum mismatch")
    files = value.get("files")
    if not isinstance(files, dict) or len(files) > MAX_FILES:
        raise ValueError("invalid worker snapshot file manifest")
    total = 0
    for name, entry in files.items():
        if (
            not persistent(name)
            or not isinstance(entry, dict)
            or set(entry) != {"size", "sha256", "kind"}
            or type(entry["size"]) is not int
            or not 0 <= entry["size"] <= MAX_FILE_BYTES
            or not isinstance(entry["sha256"], str)
            or not HASH.fullmatch(entry["sha256"])
            or entry["kind"]
            != ("sqlite" if PurePosixPath(name).name in SQLITE_NAMES else "file")
        ):
            raise ValueError("invalid worker snapshot member")
        total += entry["size"]
    if total > MAX_TOTAL_BYTES:
        raise ValueError("worker snapshot byte limit exceeded")
    return files


def _extract(
    archive: tarfile.TarFile, stage: Path, files: dict[str, dict[str, Any]]
) -> None:
    """Extract regular members manually, refusing links, traversal and duplicates."""
    seen: set[str] = set()
    for item in archive:
        if (
            item.name not in files
            or item.name in seen
            or not item.isfile()
            or item.size != files[item.name]["size"]
        ):
            raise ValueError("invalid worker archive member")
        seen.add(item.name)
        saved = stage / item.name
        saved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        stream: BinaryIO | None = archive.extractfile(item)
        if stream is None:
            raise ValueError("worker archive member missing")
        descriptor = os.open(saved, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with stream, os.fdopen(descriptor, "wb") as output:
            shutil.copyfileobj(stream, output, length=CHUNK)
            output.flush()
            os.fsync(output.fileno())
        if (
            saved.stat().st_size != item.size
            or digest(saved) != files[item.name]["sha256"]
        ):
            raise ValueError("worker member checksum mismatch")
        if files[item.name]["kind"] == "sqlite":
            _sqlite_integrity(saved)
    if seen != set(files):
        raise ValueError("worker archive member set mismatch")


def restore(snapshot: Path, target: Path) -> Path:
    """Verify hashes/SQLite integrity, then atomically publish into a new empty root.

    Args:
        snapshot: Local tar.gz and accompanying manifest chosen by the operator.
        target: Missing or empty directory; a live/nonempty/symlink root is refused.

    Returns:
        Private restored directory. Operators set uid10001 ownership before use.
    """
    if target.is_symlink() or (
        target.exists() and (not target.is_dir() or any(target.iterdir()))
    ):
        raise ValueError("restore requires a new empty directory")
    files = _manifest(snapshot)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent = target.parent.resolve()
    target = parent / target.name
    stage = Path(tempfile.mkdtemp(prefix=".worker-restore-", dir=parent))
    try:
        with tarfile.open(snapshot, "r:gz") as archive:
            _extract(archive, stage, files)
        if target.is_symlink() or (
            target.exists() and (not target.is_dir() or any(target.iterdir()))
        ):
            raise ValueError("restore target changed before publication")
        os.replace(stage, target)
        LOGGER.info("Verified worker restoration complete: %s files", len(files))
        return target
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main(argv: list[str] | None = None) -> int:
    """Run explicit local backup/isolated restore, logging no state or credentials."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    save = commands.add_parser("backup")
    save.add_argument("--source", type=Path, default=Path(".local/worker"))
    save.add_argument("--directory", type=Path, default=Path(".local/worker-backups"))
    save.add_argument("--upload", action="store_true")
    save.add_argument("--s3-prefix")
    recovered = commands.add_parser("restore")
    recovered.add_argument("snapshot", type=Path)
    recovered.add_argument("--target", type=Path, required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        if args.action == "backup":
            backup(
                args.source,
                args.directory,
                upload=args.upload,
                s3_prefix=args.s3_prefix,
            )
        else:
            restore(args.snapshot, args.target)
        return 0
    except Exception as error:
        LOGGER.error("Worker recovery operation failed (%s)", type(error).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
