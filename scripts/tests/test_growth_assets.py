"""Ensure reusable private exports cannot overwrite approved media."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

try:
    import PIL
except ImportError:
    PIL = None


@unittest.skipUnless(PIL, "Optional artwork export needs Pillow")
class GrowthAssetTest(unittest.TestCase):
    def module(self):
        spec = importlib.util.spec_from_file_location(
            "growth_assets", Path(__file__).resolve().parents[1] / "growth_assets.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_reusable_export_keeps_approved_version_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "reel-R02"
            target.mkdir()
            manifest = target / "manifest.json"
            before = json.dumps({"status": "approved", "reviewed_at": "2026-10-20"})
            manifest.write_text(before)
            with self.assertRaisesRegex(ValueError, "approved"):
                self.module().prepare_destination(root, "R02")
            self.assertEqual(manifest.read_text(), before)

    def test_asset_identity_selects_its_own_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(
                self.module().prepare_destination(root, "R02"), root / "reel-R02"
            )
            with self.assertRaises(ValueError):
                self.module().prepare_destination(root, "../approved")


if __name__ == "__main__":
    unittest.main()
