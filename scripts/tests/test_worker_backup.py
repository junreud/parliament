"""Synthetic private worker recovery tests; no AWS or production data."""

import hashlib
import io
import json
import sqlite3
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import worker_backup


class WorkerBackupTest(unittest.TestCase):
    """Verify real WAL snapshots, private artifacts and isolated safe restoration."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "worker"
        self.source.mkdir()
        self.directory = self.root / "backups"

    def test_roster_candidate_snapshot_survives_isolated_restore(self) -> None:
        candidates = self.source / "knowledge-batches"
        candidates.mkdir()
        filename = "roster_batch_" + "a" * 64 + ".json"
        original = b'{"publication":"pending_operator_review"}'
        (candidates / filename).write_bytes(original)
        snapshot = worker_backup.backup(self.source, self.directory)
        restored = self.root / "restored"
        worker_backup.restore(snapshot, restored)
        self.assertEqual(
            (restored / "knowledge-batches" / filename).read_bytes(), original
        )

    def state(self) -> None:
        """Keep committed state in live WAL connections during the snapshot."""
        ledger = sqlite3.connect(self.source / "review.sqlite3")
        self.addCleanup(ledger.close)
        ledger.execute("PRAGMA journal_mode=WAL")
        ledger.execute("PRAGMA wal_autocheckpoint=0")
        ledger.execute("CREATE TABLE costs(month TEXT PRIMARY KEY,amount TEXT)")
        ledger.execute("INSERT INTO costs VALUES('2026-10','50')")
        ledger.execute("CREATE TABLE approvals(identity TEXT PRIMARY KEY,day TEXT)")
        ledger.executemany(
            "INSERT INTO approvals VALUES(?,?)",
            [(f"synthetic-{index}", "2026-10-07") for index in range(50)],
        )
        ledger.commit()
        path = self.source / "korea" / "raw-index.sqlite3"
        path.parent.mkdir()
        index = sqlite3.connect(path)
        self.addCleanup(index.close)
        index.execute("PRAGMA journal_mode=WAL")
        index.execute(
            "CREATE TABLE raw_versions(identity TEXT,payload_hash TEXT,UNIQUE(identity,payload_hash))"
        )
        index.execute(
            "INSERT INTO raw_versions VALUES('synthetic-id','synthetic-hash')"
        )
        index.commit()
        raw = path.parent / "raw" / ("a" * 64)
        raw.mkdir(parents=True)
        (raw / ("b" * 64 + ".bin")).write_bytes(b"[SYNTHETIC] official original")
        (raw / ("b" * 64 + ".json")).write_text('{"observedAt":"2026-10-07T00:00:00Z"}')
        cache = path.parent / "summary_drafts" / ("a" * 64) / ("b" * 64)
        cache.mkdir(parents=True)
        (cache / ("c" * 64 + ".json")).write_text('{"oneLine":"[SYNTHETIC] draft"}')
        (cache / ("request_" + "d" * 64 + ".json")).write_text(
            json.dumps({"file": "c" * 64 + ".json"})
        )
        self.assertGreater((self.source / "review.sqlite3-wal").stat().st_size, 0)

    def test_wal_budget_index_and_summary_cache_restore_without_reset(self) -> None:
        self.state()
        snapshot = worker_backup.backup(self.source, self.directory)
        self.assertEqual(snapshot.stat().st_mode & 0o777, 0o600)
        self.assertEqual(
            worker_backup.manifest_path(snapshot).stat().st_mode & 0o777, 0o600
        )
        with tarfile.open(snapshot) as archive:
            self.assertFalse(
                any(name.endswith(("-wal", "-shm")) for name in archive.getnames())
            )
            self.assertTrue(
                all(item.isfile() and item.mode == 0o600 for item in archive)
            )
        target = self.root / "restored"
        worker_backup.restore(snapshot, target)
        self.assertEqual(target.stat().st_mode & 0o777, 0o700)
        with sqlite3.connect(target / "review.sqlite3") as ledger:
            self.assertEqual(
                ledger.execute("SELECT amount FROM costs").fetchone()[0], "50"
            )
            self.assertEqual(
                ledger.execute("SELECT COUNT(*) FROM approvals").fetchone()[0], 50
            )
        with sqlite3.connect(target / "korea" / "raw-index.sqlite3") as index:
            with self.assertRaises(sqlite3.IntegrityError):
                index.execute(
                    "INSERT INTO raw_versions VALUES('synthetic-id','synthetic-hash')"
                )
        self.assertTrue(list(target.rglob("request_*.json")))
        self.assertEqual(len(list(target.rglob("*.bin"))), 1)
        self.assertTrue(
            all(
                path.stat().st_mode & 0o777 == 0o600
                for path in target.rglob("*")
                if path.is_file()
            )
        )

    def test_credentials_mail_and_unknown_files_are_excluded(self) -> None:
        self.state()
        (self.source / ".env").write_text("SYNTHETIC_SECRET=never-included")
        (self.source / ".aws").mkdir()
        (self.source / ".aws" / "credentials").write_text("synthetic")
        for name in ("credentials.json", "private.pem", "login.eml", "unknown.json"):
            (self.source / name).write_text("synthetic sensitive material")
        snapshot = worker_backup.backup(self.source, self.directory)
        with tarfile.open(snapshot) as archive:
            names = archive.getnames()
        self.assertFalse(any(name.startswith(".") for name in names))
        self.assertFalse(
            any(
                "credentials" in name or name.endswith((".pem", ".eml"))
                for name in names
            )
        )
        self.assertNotIn("unknown.json", names)

    def test_knowledge_observations_extractions_and_review_packets_restore(
        self,
    ) -> None:
        database = sqlite3.connect(self.source / "pilot.sqlite3")
        self.addCleanup(database.close)
        database.execute(
            "CREATE TABLE observations(id TEXT PRIMARY KEY,payload_hash TEXT)"
        )
        database.executemany(
            "INSERT INTO observations VALUES(?,?)", [("a", "A"), ("b", "B"), ("c", "A")]
        )
        database.commit()
        extraction = self.source / "extractions" / ("a" * 64)
        extraction.mkdir(parents=True)
        (extraction / ("extract_" + "b" * 64 + ".json")).write_text(
            '{"bodyStatus":"partial"}'
        )
        packets = self.source / "knowledge-batches"
        packets.mkdir()
        (packets / ("batch_" + "c" * 64 + ".json")).write_text('{"relations":[]}')
        runs = self.source / "runs"
        runs.mkdir()
        (runs / "synthetic-job.json").write_text('{"failures":0}')
        saved = worker_backup.backup(self.source, self.directory)
        target = self.root / "restored-knowledge"
        worker_backup.restore(saved, target)
        self.assertTrue((target / "pilot.sqlite3").is_file())
        with sqlite3.connect(target / "pilot.sqlite3") as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 3
            )
        self.assertEqual(len(list(target.rglob("extract_*.json"))), 1)
        self.assertEqual(len(list(target.rglob("batch_*.json"))), 1)
        self.assertTrue((target / "runs" / "synthetic-job.json").is_file())

    def test_source_symlinks_are_rejected_without_following(self) -> None:
        self.state()
        secret = self.root / "outside.json"
        secret.write_text("synthetic secret")
        (self.source / "report.json").symlink_to(secret)
        with self.assertRaises(ValueError):
            worker_backup.backup(self.source, self.directory)
        self.assertFalse(list(self.directory.glob("*.tar.gz")))
        link = self.root / "linked-root"
        link.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(ValueError):
            worker_backup.backup(link, self.directory)

    def test_upload_failure_preserves_private_local_recovery(self) -> None:
        self.state()
        with patch.object(
            worker_backup,
            "command",
            side_effect=RuntimeError("synthetic upload failure"),
        ):
            with self.assertRaises(RuntimeError):
                worker_backup.backup(
                    self.source,
                    self.directory,
                    upload=True,
                    s3_prefix="s3://synthetic-private/backups/worker",
                )
        snapshot = next(self.directory.glob("*.tar.gz"))
        self.assertTrue(worker_backup.manifest_path(snapshot).is_file())
        worker_backup.restore(snapshot, self.root / "recovered")

    def test_s3_is_explicit_and_scoped_to_private_backup_prefix(self) -> None:
        self.state()
        with patch.object(worker_backup, "command") as command:
            worker_backup.backup(self.source, self.directory)
            command.assert_not_called()
            with self.assertRaises(ValueError):
                worker_backup.backup(
                    self.source,
                    self.directory,
                    s3_prefix="s3://synthetic-private/backups/worker",
                )
            with self.assertRaises(ValueError):
                worker_backup.backup(
                    self.source,
                    self.directory,
                    upload=True,
                    s3_prefix="s3://synthetic-private/public",
                )
            command.assert_not_called()
            worker_backup.backup(
                self.source,
                self.directory,
                upload=True,
                s3_prefix="s3://synthetic-private/backups/worker",
            )
            self.assertEqual(command.call_count, 2)
            for args in command.call_args_list:
                arguments = args.args[0]
                self.assertIn("AES256", arguments)
                self.assertNotIn("--acl", arguments)

    def test_restore_never_overwrites_nonempty_or_symlink_target(self) -> None:
        self.state()
        snapshot = worker_backup.backup(self.source, self.directory)
        target = self.root / "live"
        target.mkdir()
        (target / "keep").write_text("unchanged")
        with self.assertRaises(ValueError):
            worker_backup.restore(snapshot, target)
        self.assertEqual((target / "keep").read_text(), "unchanged")
        link = self.root / "link"
        link.symlink_to(target, target_is_directory=True)
        with self.assertRaises(ValueError):
            worker_backup.restore(snapshot, link)

    def test_archive_corruption_leaves_empty_target_untouched(self) -> None:
        self.state()
        snapshot = worker_backup.backup(self.source, self.directory)
        snapshot.write_bytes(snapshot.read_bytes() + b"corruption")
        target = self.root / "empty"
        target.mkdir()
        with self.assertRaises(ValueError):
            worker_backup.restore(snapshot, target)
        self.assertEqual(list(target.iterdir()), [])

    def test_valid_restore_atomically_replaces_only_empty_directory(self) -> None:
        self.state()
        snapshot = worker_backup.backup(self.source, self.directory)
        target = self.root / "new-empty"
        target.mkdir(mode=0o755)
        worker_backup.restore(snapshot, target)
        self.assertEqual(target.stat().st_mode & 0o777, 0o700)
        self.assertTrue((target / "review.sqlite3").is_file())

    def test_corrupt_source_sqlite_never_creates_recovery_artifact(self) -> None:
        (self.source / "review.sqlite3").write_bytes(b"synthetic invalid sqlite")
        with self.assertRaises(ValueError):
            worker_backup.backup(self.source, self.directory)
        self.assertFalse(list(self.directory.glob("*.tar.gz")))
        self.assertFalse(list(self.directory.glob(".worker-backup-*")))

    def crafted(self, name: str, raw: bytes, *, symlink: bool = False) -> Path:
        """Create a malicious but consistently hashed synthetic archive."""
        snapshot = self.root / "crafted.tar.gz"
        with tarfile.open(snapshot, "w:gz") as archive:
            item = tarfile.TarInfo(name)
            item.mode = 0o600
            if symlink:
                item.type = tarfile.SYMTYPE
                item.linkname = "../outside"
                archive.addfile(item)
            else:
                item.size = len(raw)
                archive.addfile(item, io.BytesIO(raw))
        worker_backup.manifest_path(snapshot).write_text(
            json.dumps(
                {
                    "format": 1,
                    "sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
                    "files": {
                        name: {
                            "size": len(raw),
                            "sha256": hashlib.sha256(raw).hexdigest(),
                            "kind": (
                                "sqlite"
                                if Path(name).name in worker_backup.SQLITE_NAMES
                                else "file"
                            ),
                        }
                    },
                }
            )
        )
        return snapshot

    def test_sqlite_corruption_is_verified_before_atomic_publication(self) -> None:
        snapshot = self.crafted("review.sqlite3", b"synthetic invalid sqlite")
        target = self.root / "new"
        with self.assertRaises(ValueError):
            worker_backup.restore(snapshot, target)
        self.assertFalse(target.exists())
        self.assertFalse(list(self.root.glob(".worker-restore-*")))

    def test_tar_traversal_and_link_members_are_rejected(self) -> None:
        for name, link in (("../escape", False), ("review.sqlite3", True)):
            snapshot = self.crafted(name, b"synthetic", symlink=link)
            with self.assertRaises(ValueError):
                worker_backup.restore(snapshot, self.root / "new")
            self.assertFalse((self.root / "escape").exists())

    def test_member_hash_mismatch_is_rejected_before_publication(self) -> None:
        name = "korea/raw/" + "a" * 64 + "/" + "b" * 64 + ".bin"
        snapshot = self.crafted(name, b"[SYNTHETIC] original")
        manifest = worker_backup.manifest_path(snapshot)
        data = json.loads(manifest.read_text())
        data["files"][name]["sha256"] = "0" * 64
        manifest.write_text(json.dumps(data))
        target = self.root / "new"
        with self.assertRaises(ValueError):
            worker_backup.restore(snapshot, target)
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
