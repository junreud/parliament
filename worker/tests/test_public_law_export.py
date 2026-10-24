"""Protect the boundary between private law storage and a bundled public collection."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "export_public_laws", ROOT / "scripts/export-public-laws.py"
)
assert SPEC is not None and SPEC.loader is not None
EXPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXPORT)


@pytest.fixture
def page() -> dict:
    """Return the exact public response included in the application."""
    return json.loads((ROOT / "mobile/src/data/laws.json").read_text())


def test_export_preserves_three_reviewed_records_without_enrichment(page: dict) -> None:
    assert EXPORT.validate(page) == page
    assert len(page["items"]) == 3
    assert all(len(item["evidence"]) == 6 for item in page["items"])


@pytest.mark.parametrize("field", ["rawStorageKey", "OC", "adminKey"])
def test_export_rejects_private_fields(page: dict, field: str) -> None:
    modified = copy.deepcopy(page)
    modified["items"][0][field] = "fixture-only"
    with pytest.raises(ValueError, match="unexpected_public_law_fields"):
        EXPORT.validate(modified)


def test_export_rejects_credentials_in_source_link(page: dict) -> None:
    page["items"][0]["sourceUrl"] += "&OC=fixture-only"
    with pytest.raises(ValueError, match="invalid_public_law_identity"):
        EXPORT.validate(page)


def test_export_rejects_invalid_calendar_date(page: dict) -> None:
    page["items"][0]["effectiveDate"] = "2026-02-30"
    with pytest.raises(ValueError):
        EXPORT.validate(page)


def test_export_preserves_real_empty_public_collection() -> None:
    page = {"items": [], "coverage": "공개 목록 없음", "nextCursor": None}
    assert EXPORT.validate(page) == page
