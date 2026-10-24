"""Descriptor-relative private I/O refuses symlinks beneath explicit boundaries."""

import fcntl
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _canonical_aliases(path: Path) -> Path:
    """Resolve only system /tmp and /var aliases, never user-created links."""
    absolute = path.absolute()
    for alias in (Path("/tmp"), Path("/var")):
        if absolute.is_relative_to(alias):
            return alias.resolve() / absolute.relative_to(alias)
    return absolute


@contextmanager
def _parent(
    path: Path, root: Path | None = None, *, create: bool = False
) -> Iterator[tuple[int, str]]:
    """Open every parent with O_NOFOLLOW and retain its descriptor for I/O."""
    absolute = _canonical_aliases(path)
    if ".." in absolute.parts:
        raise ValueError("unsafe private path")
    boundary = root if root is not None else Path("/")
    if not absolute.is_relative_to(boundary) or absolute == boundary:
        raise ValueError("private path escapes storage boundary")
    relative = absolute.relative_to(boundary)
    descriptor = -1
    try:
        descriptor = os.open(boundary, DIRECTORY_FLAGS)
        for component in relative.parts[:-1]:
            try:
                child = os.open(component, DIRECTORY_FLAGS, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(component, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                child = os.open(component, DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor, relative.name
    except OSError as error:
        raise ValueError("unsafe private path or symlink") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _regular(parent: int, name: str) -> None:
    """Refuse existing symlink, directory, device and special-file destinations."""
    try:
        metadata = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("unsafe private path or symlink")


def private_read(
    path: Path, *, root: Path | None = None, max_bytes: int = 10_000_000
) -> bytes:
    """Read a bounded regular private file without traversing a symlink."""
    with _parent(path, root) as (parent, name):
        _regular(parent, name)
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
        with os.fdopen(descriptor, "rb") as handle:
            value = handle.read(max_bytes + 1)
        if len(value) > max_bytes:
            raise ValueError("private file size exceeds limit")
        return value


def private_write(
    path: Path, value: bytes, *, immutable: bool = True, root: Path | None = None
) -> None:
    """Write 0600 data using openat; atomic replacement never follows links.

    Args:
        path: Explicit target path beneath the supplied storage boundary.
        value: Exact bytes to preserve.
        immutable: Require an equal existing regular file instead of replacing it.
        root: Canonical store root, or the filesystem root for explicit exports.
    """
    with _parent(path, root, create=True) as (parent, name):
        _regular(parent, name)
        if immutable:
            try:
                descriptor = os.open(
                    name,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                    dir_fd=parent,
                )
            except FileNotFoundError:
                descriptor = None
            if descriptor is not None:
                with os.fdopen(descriptor, "rb") as handle:
                    if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                        raise ValueError("unsafe private path")
                    if handle.read(len(value) + 1) != value:
                        raise ValueError("immutable snapshot conflict")
                return
        temporary = ".private-" + uuid4().hex + ".tmp"
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent,
        )
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(value)
                handle.flush()
                os.fsync(handle.fileno())
            _regular(parent, name)
            if immutable:
                try:
                    os.link(
                        temporary,
                        name,
                        src_dir_fd=parent,
                        dst_dir_fd=parent,
                        follow_symlinks=False,
                    )
                except FileExistsError:
                    descriptor = os.open(
                        name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent
                    )
                    with os.fdopen(descriptor, "rb") as handle:
                        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                            raise ValueError("unsafe private path")
                        if handle.read(len(value) + 1) != value:
                            raise ValueError("immutable snapshot conflict")
            else:
                os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
        finally:
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass


def private_database_size(path: Path, *, root: Path) -> int:
    """Return a regular private database's size without following symlinks."""
    with _parent(path, root) as (parent, name):
        _regular(parent, name)
        try:
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
        except FileNotFoundError:
            return 0
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise ValueError("unsafe database path")
            return metadata.st_size
        finally:
            os.close(descriptor)


def private_database_sidecars_checked(path: Path, *, root: Path) -> None:
    """Reject SQLite journal and WAL paths that could escape the private store."""
    with _parent(path, root) as (parent, name):
        for suffix in ("-journal", "-wal", "-shm"):
            sidecar = name + suffix
            _regular(parent, sidecar)
            try:
                metadata = os.stat(sidecar, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                continue
            if metadata.st_nlink != 1:
                raise ValueError("unsafe private database sidecar")


@contextmanager
def private_database_lock(path: Path, *, root: Path) -> Iterator[None]:
    """Hold the cross-process graph writer lock around a checked private file."""
    with _parent(path, root, create=True) as (parent, name):
        _regular(parent, name)
        lock_name = "." + name + ".lock"
        _regular(parent, lock_name)
        descriptor = os.open(
            lock_name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=parent
        )
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise ValueError("unsafe database lock path")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ValueError("pilot store busy") from error
            _regular(parent, name)
            try:
                database = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
            except FileNotFoundError:
                database = os.open(
                    name,
                    os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=parent,
                )
            try:
                metadata = os.fstat(database)
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                    raise ValueError("unsafe database path")
            finally:
                os.close(database)
            yield
        finally:
            os.close(descriptor)


@contextmanager
def private_database_snapshot(
    path: Path, *, root: Path, max_bytes: int = 64_000_000
) -> Iterator[bytes]:
    """Lock and read a checked snapshot for stores using atomic replacement."""
    if type(max_bytes) is not int or not 1 <= max_bytes <= 1_536_000_000:
        raise ValueError("invalid database snapshot read limit")
    with private_database_lock(path, root=root):
        yield private_read(path, root=root, max_bytes=max_bytes)
