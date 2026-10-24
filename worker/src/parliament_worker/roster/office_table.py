"""Discover bounded, source-local office candidates from an official table."""

import hashlib
import re
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from parliament_worker.graphrag.source_safety import contains_contact
from parliament_worker.http import validate_official_url
from parliament_worker.roster.profiles import collect_profiles

SOURCE_PREFIX = "roster_KR_OFFICE_PROFILE_CANDIDATE:"
PERSON_NAME = re.compile(r"[가-힣]{2,6}")
RECORD_KEY = re.compile(r"provisional-office-profile:[a-f0-9]{24}")
JOB_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")


def _manifest_fields(manifest: dict[str, Any], job_id: str) -> None:
    """Reject unbounded or malformed table selection before fetching."""
    if not JOB_ID.fullmatch(job_id):
        raise ValueError("invalid office table job ID")
    validate_official_url(manifest["sourceUrl"])
    for field, limit in (
        ("tableSelector", 1000),
        ("expectedCaption", 300),
        ("organizationCode", 100),
        ("organizationName", 200),
    ):
        value = manifest.get(field)
        if not isinstance(value, str) or not 1 <= len(value) <= limit:
            raise ValueError("invalid office table manifest")
    if manifest.get("currentness") != "source_current_roster":
        raise ValueError("office table must be a current official roster")
    if manifest.get("licenseStatus") not in {"unknown", "open", "restricted"}:
        raise ValueError("invalid office table usage status")


def _existing_record_keys(
    sources: list[dict[str, Any]],
    url: str,
    caption: str,
    organization_name: str,
) -> dict[tuple[str, str], str]:
    """Reuse an ID only for an exact row in the same official source."""
    by_row: dict[tuple[str, str], set[str]] = defaultdict(set)
    for source in sources:
        if not source["scope"].startswith(SOURCE_PREFIX):
            continue
        payload = source["payload"]
        document = payload["document"]
        if document.get("sourceUrl") != url:
            continue
        record_key = document.get("recordKey", "")
        if not RECORD_KEY.fullmatch(record_key):
            continue
        people = [
            entity["name"]
            for entity in payload.get("entities", [])
            if entity.get("kind") == "person"
        ]
        organizations = [
            entity["name"]
            for entity in payload.get("entities", [])
            if entity.get("kind") == "organization"
        ]
        if len(people) != 1 or organizations != [organization_name]:
            continue
        for unit in payload.get("units", []):
            text = unit.get("text", "")
            prefix = caption + " "
            if not text.startswith(prefix):
                continue
            text = text[len(prefix) :]
            role, separator, name = text.rpartition(" ")
            if separator and name == people[0] and role:
                by_row[(role, name)].add(record_key)
    if any(len(keys) != 1 for keys in by_row.values()):
        raise ValueError("ambiguous existing office table source ID")
    return {row: next(iter(keys)) for row, keys in by_row.items()}


def collect_office_table(
    manifest: dict[str, Any],
    fetcher: Callable[[str], bytes],
    output: Path,
    job_id: str,
    *,
    existing_sources: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Collect each current table row under a stable private source ID.

    Args:
        manifest: One explicit official URL, table selector, caption, and office.
        fetcher: Safe bounded official-source fetcher.
        output: Private immutable raw and receipt destination.
        job_id: New local run ID; a changed source needs a new run.
        existing_sources: Current private sources used only to reuse exact-row IDs.

    Returns:
        A profile-compatible receipt. Changed occupants have new IDs; old IDs
        remain for review and are never retired or identity-merged here.
    """
    _manifest_fields(manifest, job_id)
    url = manifest["sourceUrl"]
    raw = fetcher(url)
    soup = BeautifulSoup(raw, "html.parser")
    tables = soup.select(manifest["tableSelector"])
    if len(tables) != 1:
        raise ValueError("official office table missing or ambiguous")
    table = tables[0]
    captions = table.find_all("caption", recursive=False)
    if (
        len(captions) != 1
        or captions[0].get_text(" ", strip=True) != manifest["expectedCaption"]
    ):
        raise ValueError("official office table caption changed")
    bodies = table.find_all("tbody", recursive=False)
    if not 1 <= len(bodies) <= 100:
        raise ValueError("official office table body changed")
    rows = [
        (body_position, row_position, row)
        for body_position, body in enumerate(bodies, start=1)
        for row_position, row in enumerate(
            body.find_all("tr", recursive=False), start=1
        )
    ]
    if not 1 <= len(rows) <= 100:
        raise ValueError("official office table row count changed")
    existing = _existing_record_keys(
        existing_sources or [],
        url,
        manifest["expectedCaption"],
        manifest["organizationName"],
    )
    specs = []
    seen_rows: set[tuple[str, str]] = set()
    table_selector = manifest["tableSelector"]
    for body_position, row_position, row in rows:
        cells = row.find_all(["th", "td"], recursive=False)
        if len(cells) != 2 or cells[0].name != "th" or cells[1].name != "td":
            raise ValueError("official office table row changed")
        if cells[0].get("scope") != "row":
            raise ValueError("official office table role header changed")
        role, name = (cell.get_text(" ", strip=True) for cell in cells)
        pair = (role, name)
        if (
            not 1 <= len(role) <= 80
            or not PERSON_NAME.fullmatch(name)
            or contains_contact(role + " " + name)
            or pair in seen_rows
        ):
            raise ValueError("unsafe or duplicate official office table row")
        seen_rows.add(pair)
        digest = hashlib.sha256((url + "\0" + role + "\0" + name).encode()).hexdigest()
        source_id = existing.get(pair, "provisional-office-profile:" + digest[:24])
        row_selector = (
            f"{table_selector} > tbody:nth-of-type({body_position})"
            f" > tr:nth-of-type({row_position})"
        )
        specs.append(
            {
                "id": "office_table_" + digest[:24],
                "sourceRecordId": source_id,
                "sourceUrl": url,
                "expectedName": name,
                "organizationCode": manifest["organizationCode"],
                "organizationName": manifest["organizationName"],
                "position": role,
                "nameSelector": row_selector + " > td",
                "contextSelector": row_selector,
                "tableCaptionSelector": table_selector + " > caption",
                "currentness": manifest["currentness"],
                "licenseStatus": manifest["licenseStatus"],
            }
        )
    result = collect_profiles(specs, lambda _: raw, output, job_id, delay=0)
    if not result["complete"] or len(result["records"]) != len(rows):
        raise ValueError("official office table profile extraction incomplete")
    return result
