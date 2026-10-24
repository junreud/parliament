"""Recovery and release regressions; no network, AWS, credentials or live Docker."""

import gzip
import hashlib
import sys
import tarfile
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_release
import database_backup

SQL = b"\n".join(
    f"CREATE TABLE `{table}` (id int);\nINSERT INTO `{table}` VALUES (1);".encode()
    for table in sorted(database_backup.REQUIRED)
)


class OperationsTest(unittest.TestCase):
    """Ensure failed operations retain earlier recovery artifacts and safe images."""

    def fixed_time(self):
        """Use deterministic snapshot identities to exercise real collisions."""
        clock = patch.object(database_backup, "datetime")
        mocked = clock.start()
        mocked.now.return_value = datetime(2026, 10, 7, tzinfo=timezone.utc)
        self.addCleanup(clock.stop)

    def fake_command(self, arguments, **kwargs):
        """Emulate the dump bytes while failing explicitly requested AWS uploads."""
        if arguments[0] == "aws":
            raise RuntimeError("upload unavailable")
        kwargs["stdout"].write(SQL)

    def test_upload_failure_keeps_valid_private_local_recovery_files(self):
        self.fixed_time()
        with tempfile.TemporaryDirectory() as directory, patch.object(
            database_backup, "command", side_effect=self.fake_command
        ):
            root = Path(directory)
            with self.assertRaises(RuntimeError):
                database_backup.backup(
                    root, ["docker", "compose"], "s3://example-private/backups"
                )
            dump = next(root.glob("*.sql.gz"))
            self.assertEqual(
                database_backup.inspect_snapshot(dump),
                {name: 1 for name in database_backup.REQUIRED},
            )
            self.assertEqual(dump.stat().st_mode & 0o777, 0o600)
            self.assertTrue(dump.with_suffix(".json").exists())

    def test_same_second_retry_never_deletes_existing_snapshot_or_manifest(self):
        self.fixed_time()
        with tempfile.TemporaryDirectory() as directory, patch.object(
            database_backup, "command", side_effect=self.fake_command
        ):
            root = Path(directory)
            path = database_backup.backup(root, ["docker"], None)
            prior = (path.read_bytes(), path.with_suffix(".json").read_bytes())
            with self.assertRaises(FileExistsError):
                database_backup.backup(root, ["docker"], None)
            self.assertEqual(
                prior, (path.read_bytes(), path.with_suffix(".json").read_bytes())
            )

    def test_dump_view_placeholders_are_not_mistaken_for_empty_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "views.sql.gz"
            with gzip.open(path, "wb") as source:
                source.write(
                    SQL
                    + b"\n-- Temporary table structure for view `current_people`\nCREATE TABLE `current_people` (id int);\n-- Final view structure for view `current_people`\n"
                )
            self.assertNotIn("current_people", database_backup.inspect_snapshot(path))

    def test_release_includes_verified_compose_bytes_as_executable_regular_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "compose"
            binary.write_bytes(b"synthetic verified executable bytes")
            binary.chmod(0o600)
            link = root / "compose-link"
            link.symlink_to(binary)
            output = root / "release.tar.gz"
            images = {
                f"{name}_IMAGE": "example/image@sha256:" + "a" * 64
                for name in ("BACKEND", "WEB", "WORKER", "MYSQL")
            }
            build_release.build(
                output, images, link, hashlib.sha256(binary.read_bytes()).hexdigest()
            )
            with tarfile.open(output) as archive:
                member = archive.getmember("bin/docker-compose")
                self.assertTrue(member.isfile())
                self.assertEqual(member.mode, 0o755)
                self.assertEqual(
                    archive.extractfile(member).read(), binary.read_bytes()
                )
                self.assertNotIn(".env", archive.getnames())
                configuration = (
                    archive.extractfile("compose.production.yml").read().decode()
                )
                self.assertNotIn("immutable digest required", configuration)


if __name__ == "__main__":
    unittest.main()
