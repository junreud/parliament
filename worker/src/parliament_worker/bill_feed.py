"""Parse stable bill identities from the official legislative-status board."""

import hashlib
import json
import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup, Tag

from parliament_worker.graphrag.source_safety import contact_free_prefix
from parliament_worker.http import validate_official_url
from parliament_worker.knowledge.review import validate_batch

DETAIL_PATH = re.compile(r"/gcom/nsmLmSts/out/(\d{7})/detailRP\Z")
BASE_URL = "https://opinion.lawmaking.go.kr"


def _text(node: Tag | None) -> str:
    """Return the visible source field without HTML markup."""
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""


def parse_bill_listing(raw: bytes) -> list[dict[str, str]]:
    """Read exact bill numbers from one official list page.

    Args:
        raw: Original official HTML response bytes.

    Returns:
        Source-local number, title and stable detail URL for each row.

    Raises:
        ValueError: Expected structure or a row's URL/printed number disagrees.
    """
    rows, _ = _parse_bill_listing(raw, hold_mismatches=False)
    return rows


def parse_bill_listing_with_holds(
    raw: bytes,
) -> tuple[list[dict[str, str]], list[dict[str, str | int]]]:
    """Preserve valid rows while holding one conflicting printed number.

    Args:
        raw: Original official HTML response bytes.

    Returns:
        Valid source rows and the exact position and values of one held row.

    Raises:
        ValueError: The page structure changed or multiple numbers conflict.
    """
    return _parse_bill_listing(raw, hold_mismatches=True)


def _parse_bill_listing(
    raw: bytes, *, hold_mismatches: bool
) -> tuple[list[dict[str, str]], list[dict[str, str | int]]]:
    """Parse one listing under strict or single-row reviewable policy."""
    soup = BeautifulSoup(raw, "html.parser")
    rows: list[dict[str, str]] = []
    holds: list[dict[str, str | int]] = []
    seen: set[str] = set()
    for row_number, cell in enumerate(soup.select("td.subject"), start=1):
        link = cell.select_one("a[href]")
        if not isinstance(link, Tag):
            raise ValueError("bill listing link missing")
        path = str(link.get("href", ""))
        match = DETAIL_PATH.fullmatch(path)
        if match is None:
            raise ValueError("bill listing detail path changed")
        number = match.group(1)
        parent = cell.find_parent("tr")
        number_cell = (
            next(
                (
                    item
                    for item in parent.select("td[data-th]")
                    if "의안번호" in str(item.get("data-th", ""))
                ),
                None,
            )
            if isinstance(parent, Tag)
            else None
        )
        printed_numbers = (
            re.findall(r"(?<!\d)\d{7}(?!\d)", _text(number_cell))
            if number_cell is not None
            else []
        )
        if not printed_numbers:
            raise ValueError("bill listing number mismatch")
        if printed_numbers[0] != number:
            if not hold_mismatches:
                raise ValueError("bill listing number mismatch")
            holds.append(
                {
                    "row": row_number,
                    "printedNumber": printed_numbers[0],
                    "linkNumber": number,
                }
            )
            if len(holds) > 1:
                raise ValueError("multiple bill listing number mismatches")
            continue
        title = _text(link)
        if not title or number in seen:
            raise ValueError("bill listing title or duplicate number invalid")
        seen.add(number)
        url = BASE_URL + path
        validate_official_url(url)
        rows.append({"number": number, "title": title, "url": url})
    if not rows:
        raise ValueError("bill listing structure missing")
    return rows, holds


def parse_last_page(raw: bytes) -> int:
    """Read the board's explicit final-page link for bounded reconciliation."""
    soup = BeautifulSoup(raw, "html.parser")
    last = soup.select_one(".pagination a.icoCnt_last[href]")
    if not isinstance(last, Tag):
        raise ValueError("bill listing pagination missing")
    href = str(last.get("href", ""))
    value = parse_qs(urlsplit(href).query).get("pageIndex", [""])[0]
    if not value.isdigit() or not 1 <= int(value) <= 100_000:
        raise ValueError("invalid bill listing final page")
    return int(value)


def parse_bill_detail(raw: bytes, number: str) -> dict[str, Any]:
    """Extract only title, printed bill identity, and proposal text.

    Args:
        raw: Original official detail HTML response bytes.
        number: Seven-digit identity from a validated listing link.

    Returns:
        The text fields as printed; author names remain unlinked strings.
    """
    if not re.fullmatch(r"\d{7}", number):
        raise ValueError("invalid bill number")
    soup = BeautifulSoup(raw, "html.parser")
    title = _text(soup.select_one(".subjectHead_tit"))
    fields: dict[str, Tag] = {}
    for heading in soup.select("th[scope=row]"):
        if not isinstance(heading, Tag):
            continue
        value = heading.find_next_sibling("td")
        if isinstance(value, Tag):
            fields[_text(heading)] = value
    proposal = _text(fields.get("발의정보"))
    if not title or not re.search(rf"제{number}호(?!\d)", proposal):
        raise ValueError("bill detail title or number mismatch")
    summary = _text(fields.get("제안이유 및 주요내용"))
    return {"title": title, "proposal": proposal, "summary": summary}


def _digest(value: Any) -> str:
    """Hash a normalized extraction or immutable local identity."""
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def batch_from_bill_detail(
    number: str, detail: dict[str, str], raw: bytes, observed_at: str
) -> dict[str, Any]:
    """Build a private bill-only graph candidate from one official revision.

    Args:
        number: Validated seven-digit Assembly bill number.
        detail: Parsed official detail fields for this same number.
        raw: Original detail HTML retained locally by the caller.
        observed_at: Timestamp of the source observation.

    Returns:
        Versioned knowledge batch without inferred people or actions.
    """
    if not re.fullmatch(r"\d{7}", number) or not re.search(
        rf"제{number}호(?!\d)", detail["proposal"]
    ):
        raise ValueError("bill number and detail disagree")
    raw_hash = hashlib.sha256(raw).hexdigest()
    extraction = "billfeed_v2_" + _digest(detail)
    document_id = "doc-bill-" + number
    evidence = []
    segments = []
    for field in ("title", "proposal", "summary"):
        text = detail[field]
        if not text:
            continue
        segment_id = "bill_" + field
        segments.append(
            {
                "id": segment_id,
                "text": text,
                "locator": (
                    "html:.subjectHead_tit"
                    if field == "title"
                    else "html:th[scope=row]="
                    + ("발의정보" if field == "proposal" else "제안이유 및 주요내용")
                ),
                "mentions": [],
            }
        )
        selected = contact_free_prefix(text)[:5000]
        if selected:
            evidence.append(
                {
                    "id": "bill_ev_" + _digest([number, raw_hash, extraction, field]),
                    "documentId": document_id,
                    "documentVersion": raw_hash,
                    "extractionVersion": extraction,
                    "segmentId": segment_id,
                    "start": 0,
                    "end": len(selected),
                }
            )
    if not evidence:
        raise ValueError("bill detail has no safe source evidence")
    url = BASE_URL + f"/gcom/nsmLmSts/out/{number}/detailRP"
    document = {
        "id": document_id,
        "version": raw_hash,
        "sourceKey": "lawmaking-bill-detail",
        "recordKey": number,
        "sourceUrl": validate_official_url(url),
        "title": detail["title"],
        "format": "html",
        "bodyStatus": "available" if detail["summary"] else "partial",
        "licenseStatus": "unknown",
        "publishedAt": None,
        "collectedAt": observed_at,
        "observedAt": observed_at,
        "rawStorageKey": "raw/bills/" + raw_hash + ".html",
        "extractionVersion": extraction,
        "datePrecision": "unknown",
        "observationId": "bill_obs_" + _digest([number, raw_hash, observed_at]),
        "segments": segments,
    }
    batch = {
        "id": "bill_batch_" + _digest([number, raw_hash, extraction, observed_at]),
        "issueId": "current-bills",
        "entities": [
            {
                "id": "bill-" + number,
                "kind": "bill",
                "name": detail["title"],
                "identifiers": [{"namespace": "ASSEMBLY_BILL_NUMBER", "value": number}],
                "facts": [],
                "tenures": [],
            }
        ],
        "documents": [document],
        "evidence": evidence,
        "relations": [],
        "activities": [],
        "contexts": [],
    }
    validate_batch(batch)
    return batch
