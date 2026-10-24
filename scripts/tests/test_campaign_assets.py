"""Check actual publication assets before using the social template."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from PIL import Image
except ImportError:
    Image = None

ROOT = Path(__file__).resolve().parents[2]
CAN_EXPORT = (
    Image is not None
    and Path("/System/Library/Fonts/Supplemental/AppleMyungjo.ttf").exists()
)
MODULE = None
if CAN_EXPORT:
    SPEC = importlib.util.spec_from_file_location(
        "campaign_assets", ROOT / "scripts/campaign_assets.py"
    )
    MODULE = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(MODULE)


@unittest.skipUnless(
    CAN_EXPORT, "Optional export requires Pillow and licensed macOS system fonts"
)
class CampaignAssetTest(unittest.TestCase):
    """Verify export dimensions, review disclosure, and text safety."""

    def test_export_has_upload_dimensions_and_honest_review_label(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            stem = Path(temporary) / "B01-01"
            MODULE.render_card(
                stem,
                ["헌법은 어떻게 바뀔까?"],
                ["공식 절차를 확인합니다."],
                ["대한민국헌법 제128~130조"],
                1,
                True,
            )
            with Image.open(stem.with_suffix(".png")) as image:
                self.assertEqual(image.size, (1080, 1350))
            svg = stem.with_suffix(".svg").read_text()
            self.assertIn("검토 전 · 초안", svg)
            self.assertIn("@flow_goverment", svg)
            self.assertIn("1 / 5", svg)

    def test_text_that_overflows_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "exceeds"):
                MODULE.render_card(
                    Path(temporary) / "bad", ["긴제목" * 80], [], [], 1, True
                )

    def test_export_preserves_explicit_approval_without_claiming_publication(
        self,
    ) -> None:
        dossiers = json.loads((ROOT / "web/src/data/editorial-issues.json").read_text())
        approved, pending, incomplete = dossiers["issues"]
        approved.update(reviewStatus="reviewed", reviewedAt="2026-10-18T09:30:00+09:00")
        pending["reviewStatus"] = "human-review-pending"
        pending.pop("reviewedAt", None)
        incomplete["reviewStatus"] = "reviewed"
        incomplete.pop("reviewedAt", None)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "web/src/data/editorial-issues.json"
            source.parent.mkdir(parents=True)
            source.write_text(json.dumps(dossiers, ensure_ascii=False))
            output = root / "assets"
            with patch.object(MODULE, "ROOT", root), patch.object(
                MODULE, "OUTPUT", output
            ):
                MODULE.main()
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest[0]["status"], "approved-awaiting-release")
            self.assertFalse(manifest[0]["scheduled"])
            self.assertIsNone(manifest[0]["publicUrl"])
            self.assertNotIn("검토 전", (output / "B01/B01-01.svg").read_text())
            self.assertNotIn("검토 전", (output / "B01/caption.txt").read_text())
            for asset in ["B02", "B03"]:
                self.assertIn(
                    "검토 전", (output / asset / f"{asset}-01.svg").read_text()
                )


if __name__ == "__main__":
    unittest.main()
