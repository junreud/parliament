"""Private MySQL snapshots and isolated restore verification for the beta service."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import os
import re
import secrets
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

LOGGER = logging.getLogger(__name__)
REQUIRED = {
    "parliament_source_record",
    "tracking_event_version",
    "tracking_mail_outbox",
}


def command(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess:
    """Run a bounded operation without including output or credentials in failures."""
    try:
        return subprocess.run(arguments, check=True, timeout=180, **kwargs)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"operation failed: {arguments[0]}") from error


def private_write(path: Path, content: bytes) -> None:
    """Create a new owner-only file, refusing to overwrite an existing snapshot."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(content)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def inspect_snapshot(path: Path) -> dict[str, int]:
    """Count individual inserts from our single-row dump format inside its snapshot."""
    tables: dict[str, int] = {}
    views: set[str] = set()
    with gzip.open(path, "rt", encoding="utf-8") as source:
        for line in source:
            view = re.match(r"-- .*structure for view `([A-Za-z0-9_]+)`", line)
            if view:
                views.add(view.group(1))
                tables.pop(view.group(1), None)
            created = re.match(r"CREATE TABLE `([A-Za-z0-9_]+)`", line)
            inserted = re.match(r"INSERT INTO `([A-Za-z0-9_]+)` VALUES", line)
            if created and created.group(1) not in views:
                tables.setdefault(created.group(1), 0)
            if inserted:
                tables[inserted.group(1)] = tables.get(inserted.group(1), 0) + 1
    if not REQUIRED.issubset(tables):
        raise RuntimeError(
            "snapshot is missing service tables; apply migrations before backup"
        )
    return tables


def checksum(path: Path) -> str:
    """Hash snapshots using bounded memory."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def backup(directory: Path, compose: list[str], s3_prefix: str | None) -> Path:
    """Capture all versions and queues with one consistent InnoDB snapshot."""
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"parliament-{stamp}.sql.gz"
    arguments = compose + [
        "exec",
        "-T",
        "mysql",
        "sh",
        "-c",
        'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot '
        "--single-transaction --quick --skip-extended-insert --routines --triggers "
        '--hex-blob --set-gtid-purged=OFF "$MYSQL_DATABASE"',
    ]
    manifest = path.with_suffix(".json")
    owned_dump = owned_manifest = False
    try:
        with tempfile.TemporaryFile() as dump:
            command(arguments, stdout=dump, stderr=subprocess.DEVNULL)
            dump.seek(0)
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            owned_dump = True
            with os.fdopen(descriptor, "wb") as target, gzip.GzipFile(
                fileobj=target, mode="wb"
            ) as archive:
                while chunk := dump.read(1024 * 1024):
                    archive.write(chunk)
        tables = inspect_snapshot(path)
        private_write(
            manifest,
            json.dumps(
                {
                    "format": 1,
                    "createdAt": stamp,
                    "sha256": checksum(path),
                    "tables": tables,
                    "restoreVerified": False,
                },
                indent=2,
            ).encode(),
        )
        owned_manifest = True
    except BaseException:
        if owned_dump:
            path.unlink(missing_ok=True)
        if owned_manifest:
            manifest.unlink(missing_ok=True)
        raise
    # Preserve the validated local recovery copy if external upload fails.
    if s3_prefix:
        if not re.fullmatch(
            r"s3://[a-z0-9.-]+/backups(?:/[A-Za-z0-9/_-]+)?", s3_prefix
        ):
            raise ValueError("private backup destination must be an S3 backups/ prefix")
        for item in (path, manifest):
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
                ],
                stdout=subprocess.DEVNULL,
            )
    LOGGER.info("created private snapshot: %s", path)
    return path


def verify_restore(path: Path, image: str) -> None:
    """Restore only into a fresh container with no host port or existing volume."""
    manifest_path = path.with_suffix(".json")
    manifest = json.loads(manifest_path.read_text())
    if checksum(path) != manifest["sha256"]:
        raise ValueError("snapshot checksum mismatch")
    if inspect_snapshot(path) != manifest["tables"]:
        raise ValueError("snapshot row manifest mismatch")
    name = "parliament-restore-" + secrets.token_hex(6)
    environment = dict(
        os.environ,
        MYSQL_ROOT_PASSWORD=secrets.token_urlsafe(32),
        MYSQL_PASSWORD=secrets.token_urlsafe(32),
    )
    try:
        command(
            [
                "docker",
                "run",
                "-d",
                "--name",
                name,
                "--network",
                "none",
                "-e",
                "MYSQL_ROOT_PASSWORD",
                "-e",
                "MYSQL_DATABASE=parliament",
                "-e",
                "MYSQL_USER=parliament",
                "-e",
                "MYSQL_PASSWORD",
                image,
            ],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        ready = [
            "docker",
            "exec",
            name,
            "sh",
            "-c",
            'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqladmin ping -h localhost -uroot --silent',
        ]
        for _ in range(60):
            result = subprocess.run(
                ready, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5
            )
            if result.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("isolated restore database did not start")
        with tempfile.TemporaryFile() as expanded, gzip.open(path, "rb") as source:
            while chunk := source.read(1024 * 1024):
                expanded.write(chunk)
            expanded.seek(0)
            command(
                [
                    "docker",
                    "exec",
                    "-i",
                    name,
                    "sh",
                    "-c",
                    'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot parliament',
                ],
                stdin=expanded,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        for table, expected in manifest["tables"].items():
            if not re.fullmatch(r"[A-Za-z0-9_]+", table):
                raise ValueError("invalid manifest table")
            query = f"SELECT COUNT(*) FROM `{table}`; CHECK TABLE `{table}`;"
            result = command(
                [
                    "docker",
                    "exec",
                    "-i",
                    name,
                    "sh",
                    "-c",
                    'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -BN parliament',
                ],
                input=query.encode(),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            lines = result.stdout.decode().splitlines()
            if int(lines[0]) != expected or not lines[-1].endswith("\tstatus\tOK"):
                raise RuntimeError(f"restored table verification failed: {table}")
        verification = path.with_suffix(".restore.json")
        private_write(
            verification,
            json.dumps(
                {
                    "sha256": manifest["sha256"],
                    "verifiedAt": datetime.now(timezone.utc).isoformat(),
                    "tables": manifest["tables"],
                    "isolated": True,
                },
                indent=2,
            ).encode(),
        )
        LOGGER.info(
            "isolated restoration passed for %s tables", len(manifest["tables"])
        )
    finally:
        try:
            command(
                ["docker", "rm", "-f", "-v", name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except RuntimeError:
            LOGGER.warning("isolated restore cleanup requires attention: %s", name)


def main() -> None:
    """Run backup or isolated restoration; live replacement is deliberately separate."""
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="action", required=True)
    save = subcommands.add_parser("backup")
    save.add_argument("--directory", type=Path, default=Path(".local/backups"))
    save.add_argument("--compose-file", default="docker-compose.yml")
    save.add_argument(
        "--compose-binary", help="Pinned standalone Compose executable for the server"
    )
    save.add_argument("--s3-prefix")
    restore = subcommands.add_parser("verify-restore")
    restore.add_argument("snapshot", type=Path)
    restore.add_argument("--image", default="mysql:8.4")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.action == "backup":
        compose = (
            [args.compose_binary] if args.compose_binary else ["docker", "compose"]
        )
        backup(args.directory, compose + ["-f", args.compose_file], args.s3_prefix)
    else:
        verify_restore(args.snapshot, args.image)


if __name__ == "__main__":
    main()
