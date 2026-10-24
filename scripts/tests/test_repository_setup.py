"""Check clean-clone initialization and the public Git boundary."""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.bootstrap_repository import initialize
from scripts.check_repository import prohibited_path


class RepositorySetupTest(unittest.TestCase):
    """Keep local operator inputs private and untouched by initialization."""

    def test_bootstrap_creates_only_missing_runtime_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in [
                "src/main/resources/knowledge/issue-readings.example.json",
                "web/src/data/editorial-issues.example.json",
                "mobile/src/data/radar.example.json",
            ]:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"synthetic": True}))
            created = initialize(root)
            self.assertEqual(len(created), 3)
            self.assertEqual(initialize(root), [])
            for path in created:
                self.assertEqual(json.loads(path.read_text()), {"synthetic": True})

    def test_bootstrap_preserves_existing_private_input_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder, basename in [
                ("src/main/resources/knowledge", "issue-readings"),
                ("web/src/data", "editorial-issues"),
                ("mobile/src/data", "radar"),
            ]:
                parent = root / folder
                parent.mkdir(parents=True)
                (parent / f"{basename}.example.json").write_text("{}")
                (parent / f"{basename}.json").write_bytes(b"private local input")
            self.assertEqual(initialize(root), [])
            self.assertEqual(
                (root / "web/src/data/editorial-issues.json").read_bytes(),
                b"private local input",
            )

    def test_public_guard_blocks_forced_private_inputs(self) -> None:
        for name in [
            ".env",
            "web/.env.production",
            "nested/.local/source.json",
            "worker/manifests/current-central-profiles.json",
            "web/src/data/editorial-issues.json",
            "src/main/resources/knowledge/issue-readings.json",
            "mobile/src/data/radar.json",
            "docs/marketing/beta-4w/approvals/owner.json",
            "backup.sqlite3",
            "mobile/artifacts/screenshot.png",
            "certificates/company.pem",
        ]:
            with self.subTest(path=name):
                self.assertTrue(prohibited_path(name))

    def test_public_guard_allows_sources_and_explicit_examples(self) -> None:
        for name in [
            ".env.example",
            "web/.env.example",
            "web/src/data/editorial-issues.example.json",
            "src/main/resources/knowledge/issue-readings.example.json",
            "mobile/src/data/radar.example.json",
            "docs/development/github-workflow.md",
            "src/main/resources/sql/schema-tracking.sql",
            "worker/tests/fixtures/president-detail.html",
            "mobile/android/gradle/wrapper/gradle-wrapper.jar",
        ]:
            with self.subTest(path=name):
                self.assertFalse(prohibited_path(name))
