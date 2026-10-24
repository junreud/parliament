"""Bounded official bill discovery into private GraphRAG candidate batches."""

import hashlib
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from parliament_worker.bill_feed import (
    BASE_URL,
    batch_from_bill_detail,
    parse_bill_detail,
    parse_bill_listing,
    parse_bill_listing_with_holds,
    parse_last_page,
)
from parliament_worker.graphrag.inputs import read_sources, sources_from_batch
from parliament_worker.http import validate_official_url
from parliament_worker.knowledge.files import private_read, private_write
from parliament_worker.knowledge.review import validate_batch


def _page_url(page: int) -> str:
    """Build a bounded board URL with its ten-page block position."""
    if not 1 <= page <= 100_000:
        raise ValueError("invalid bill page")
    block = ((page - 1) // 10) * 10 + 1
    return validate_official_url(
        BASE_URL + f"/gcom/nsmLmSts/out/?pageIndex={page}&blockStartPage={block}"
    )


def _read_cursor(state_dir: Path) -> int:
    """Resume the last fully successful historical sweep."""
    path = state_dir / "cursor.json"
    if not path.exists():
        return 2
    value = json.loads(private_read(path, max_bytes=1000))
    page = value.get("nextSweepPage")
    if type(page) is not int or not 2 <= page <= 100_000:
        raise ValueError("invalid bill sweep cursor")
    return page


def _save_raw(root: Path, area: str, raw: bytes) -> str:
    """Keep one immutable raw response per content hash."""
    digest = hashlib.sha256(raw).hexdigest()
    private_write(root / "raw" / area / (digest + ".html"), raw)
    return digest


def _merged_batch(batches: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep many changed bills in one bounded immutable input file."""
    ordered = sorted(batches, key=lambda item: item["documents"][0]["recordKey"])
    content: dict[str, Any] = {
        "issueId": "current-bills",
        "entities": [],
        "documents": [],
        "evidence": [],
        "relations": [],
        "activities": [],
        "contexts": [],
    }
    for batch in ordered:
        for field in (
            "entities",
            "documents",
            "evidence",
            "relations",
            "activities",
            "contexts",
        ):
            content[field].extend(batch[field])
    digest = hashlib.sha256(
        json.dumps([batch["id"] for batch in ordered], sort_keys=True).encode()
    ).hexdigest()
    result = {"id": "bill_feed_batch_" + digest, **content}
    validate_batch(result)
    return result


def collect_bill_cycle(
    fetcher: Callable[[str], bytes],
    graph_input: Path,
    state_dir: Path,
    graph_sources: list[dict[str, Any]],
    *,
    observed_at: str,
    hot_pages: int = 1,
    sweep_pages: int = 1,
    sweep_start: int | None = None,
    request_gap_seconds: float = 0.2,
) -> dict[str, Any]:
    """Revisit recent bills and advance one bounded historical sweep.

    Args:
        fetcher: Existing allowlisted, bounded public HTTP reader.
        graph_input: Already watched private GraphRAG batch directory.
        state_dir: Private raw-list and sweep-cursor directory.
        graph_sources: Current private graph sources for curated collision holds.
        observed_at: Observation timestamp; not a proposal or publication date.
        hot_pages: Newest pages revisited on every cycle.
        sweep_pages: Additional older pages to reconcile per cycle.
        sweep_start: Explicit historical page for a bounded correction replay.
        request_gap_seconds: Minimum quiet time between detail reads.

    Returns:
        Counts, exact staged batch, review holds and bounded failure categories.
    """
    if (
        graph_input.is_symlink()
        or not graph_input.is_dir()
        or state_dir.is_symlink()
        or not state_dir.is_dir()
        or not 1 <= hot_pages <= 3
        or not 0 <= sweep_pages <= 10
        or (sweep_start is not None and not 2 <= sweep_start <= 100_000)
        or not 0 <= request_gap_seconds <= 10
    ):
        raise ValueError("unsafe or unbounded bill collection configuration")
    cursor = _read_cursor(state_dir)
    report: dict[str, Any] = {
        "schema": "parliament-bill-graph-cycle-v1",
        "observedAt": observed_at,
        "public": False,
        "lastPage": None,
        "visitedPages": [],
        "nextSweepPage": cursor,
        "stagedBillCount": 0,
        "unchangedBillCount": 0,
        "rawChangedSemanticSame": 0,
        "curatedHold": [],
        "failures": [],
        "stagedBatchFile": None,
    }
    try:
        first_raw = fetcher(_page_url(1))
        _save_raw(state_dir, "lists", first_raw)
        last_page = parse_last_page(first_raw)
        first_rows = parse_bill_listing(first_raw)
    except (httpx.HTTPError, OSError, ValueError, KeyError, TimeoutError) as error:
        report["failures"].append(
            {"stage": "first_page", "category": type(error).__name__}
        )
        return report
    report["lastPage"] = last_page
    sequential_sweep = sweep_start is None or sweep_start == cursor
    sweep_start = sweep_start if sweep_start is not None else cursor
    if sweep_start > last_page:
        sweep_start = 2
    hot = list(range(1, min(hot_pages, last_page) + 1))
    sweep = list(range(sweep_start, min(sweep_start + sweep_pages - 1, last_page) + 1))
    pages = list(dict.fromkeys(hot + sweep))
    rows: dict[str, dict[str, str]] = {}
    for page in pages:
        try:
            if page == 1:
                current = first_rows
            else:
                listing_raw = fetcher(_page_url(page))
                _save_raw(state_dir, "lists", listing_raw)
                current, holds = parse_bill_listing_with_holds(listing_raw)
                for hold in holds:
                    report["failures"].append(
                        {
                            "stage": "listing_row",
                            "page": page,
                            "category": "bill_number_mismatch",
                            **hold,
                        }
                    )
        except (httpx.HTTPError, OSError, ValueError, KeyError, TimeoutError) as error:
            report["failures"].append(
                {"stage": "listing", "page": page, "category": type(error).__name__}
            )
            continue
        report["visitedPages"].append(page)
        for row in current:
            rows.setdefault(row["number"], row)
    known = {item["scope"]: item for item in graph_sources}
    if list(graph_input.glob("*.json")):
        known.update({item["scope"]: item for item in read_sources([graph_input])})
    changed: list[dict[str, Any]] = []
    for number, row in rows.items():
        if request_gap_seconds:
            time.sleep(request_gap_seconds)
        try:
            raw = fetcher(row["url"])
            _save_raw(state_dir, "details", raw)
            detail = parse_bill_detail(raw, number)
            batch = batch_from_bill_detail(number, detail, raw, observed_at)
            source = sources_from_batch(batch)[0]
        except (httpx.HTTPError, OSError, ValueError, KeyError, TimeoutError) as error:
            report["failures"].append(
                {"stage": "detail", "number": number, "category": type(error).__name__}
            )
            continue
        scope = source["scope"]
        previous = known.get(scope)
        if previous and not previous["payload"]["document"][
            "extractionVersion"
        ].startswith(("billfeed_v1_", "billfeed_v2_")):
            report["curatedHold"].append(number)
            continue
        if (
            previous
            and previous["payload"]["document"]["extractionVersion"]
            == source["payload"]["document"]["extractionVersion"]
        ):
            report["unchangedBillCount"] += 1
            if (
                previous["payload"]["document"]["version"]
                != source["payload"]["document"]["version"]
            ):
                report["rawChangedSemanticSame"] += 1
            continue
        if previous and previous["fingerprint"] == source["fingerprint"]:
            report["unchangedBillCount"] += 1
            continue
        _save_raw(graph_input, "bills", raw)
        changed.append(batch)
    if changed:
        merged = _merged_batch(changed)
        path = graph_input / (merged["id"] + ".json")
        private_write(
            path,
            json.dumps(merged, ensure_ascii=False, sort_keys=True, indent=2).encode(),
        )
        report["stagedBillCount"] = len(changed)
        report["stagedBatchFile"] = path.name
    if not report["failures"] and sequential_sweep:
        next_page = sweep_start + sweep_pages
        report["nextSweepPage"] = 2 if next_page > last_page else next_page
        private_write(
            state_dir / "cursor.json",
            json.dumps({"nextSweepPage": report["nextSweepPage"]}).encode(),
            immutable=False,
        )
    return report
