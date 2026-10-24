"""President public board and schedule JSON adapters linked by official HTML."""

import json
import re
from collections.abc import Callable
from datetime import datetime, timedelta
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

from parliament_worker.models import SEOUL, CollectionResult, Listing, SourceDocument
from parliament_worker.parsing import clean_text, parse_date

BASE = "https://www.president.go.kr"


def parse_board(source: str, raw: bytes) -> list[Listing]:
    """Parse BBS_CD/WRITE_DT from the official board AJAX response."""
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("official board structure missing")
    data = data.get("data", data)
    if not isinstance(data, dict) or not isinstance(data.get("list"), list):
        raise ValueError("official board structure missing")
    section = "speeches" if source == "president-speeches" else "briefings"
    result = []
    for row in data["list"]:
        if not isinstance(row, dict):
            raise ValueError("official board row structure invalid")
        key = str(row.get("BBS_CD", ""))
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", key):
            continue
        date = parse_date(str(row.get("WRITE_DT") or row.get("WRITE_DATE", "")))
        result.append(
            Listing(
                key,
                f"{BASE}/{section}/{key}",
                clean_text(str(row.get("SUBJECT", ""))),
                date,
                "대통령실",
            )
        )
    return result


def parse_schedule(raw: bytes, collected: datetime) -> list[SourceDocument]:
    """Retain actual occurrences and explicit registration publication timestamps."""
    response = json.loads(raw)
    if not isinstance(response, dict):
        raise ValueError("official schedule structure missing")
    data = response.get("data", {})
    if not isinstance(data, dict) or not isinstance(data.get("list"), list):
        raise ValueError("official schedule structure missing")
    documents = []
    for row in data["list"]:
        if not isinstance(row, dict):
            raise ValueError("official schedule row structure invalid")
        if row.get("SCH_TYPE") not in ("R0201", "R0203"):
            continue
        day = parse_date(str(row.get("SCH_DT", "")))
        if day is None:
            continue
        clock = str(row.get("SCH_TIME", ""))
        if re.fullmatch(r"\d{2}:\d{2}", clock):
            hour, minute = (int(value) for value in clock.split(":"))
            if hour < 24 and minute < 60:
                day = day.replace(hour=hour, minute=minute)
        key = str(row.get("SCHEDULE_SEQ") or row.get("SCH_SEQ", ""))
        if not key or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", key):
            raise ValueError("official schedule identity missing")
        registered = row.get("REG_DATE")
        publication = None
        if isinstance(registered, (int, float)) and not isinstance(registered, bool):
            try:
                publication = datetime.fromtimestamp(registered / 1000, tz=SEOUL)
            except (ValueError, OverflowError, OSError):
                pass
        documents.append(
            SourceDocument(
                "president-schedule",
                key,
                f"{BASE}/schedule/{day:%Y%m%d}",
                clean_text(str(row.get("SUBJECT", ""))),
                clean_text(str(row.get("SUBJECT", ""))),
                publication,
                collected,
                f"JSON data.list SCHEDULE_SEQ={key}",
                agency="대통령실",
                raw=raw,
                occurred_at=day,
                license_status="unknown",
            )
        )
    return documents


def collect_president(
    source: str,
    fetch: Callable[..., bytes],
    now: datetime,
    *,
    max_pages: int,
    days: int,
    max_records: int,
) -> CollectionResult:
    """Read official form identifiers instead of guessing board IDs."""
    from parliament_worker.connectors import SOURCES, parse_detail

    result = CollectionResult()
    cutoff = now - timedelta(days=days)
    try:
        if source == "president-schedule":
            # Four months cover at most 90 days, including a partial boundary month.
            month = now.replace(day=1)
            for _ in range(min(max_pages, 4)):
                params = urlencode(
                    {"pSiteNo": "2", "pYear": month.year, "pMonth": f"{month.month:02}"}
                )
                raw = fetch(f"{BASE}/ajaxf/frSchedule/getSchedule.do?{params}")
                result.pages += 1
                result.documents.extend(
                    doc
                    for doc in parse_schedule(raw, now)
                    if doc.occurred_at and cutoff <= doc.occurred_at <= now
                )
                month = (month - timedelta(days=1)).replace(day=1)
                if month < cutoff.replace(day=1):
                    break
            result.documents = result.documents[:max_records]
            return result
        page_html = fetch(SOURCES[source])
        soup = BeautifulSoup(page_html, "html.parser")
        fields = {
            str(node.get("name")): str(node.get("value", ""))
            for node in soup.select("#sendForm input[name]")
        }
        required = ("MENU_CD", "CONTENTS_CD", "pSiteNo", "pBoardSeq", "SHORT_URL")
        if not all(fields.get(field) for field in required):
            raise ValueError("official board form structure missing")
        seen: set[str] = set()
        for page in range(1, max_pages + 1):
            fields.update({"pageNo": str(page), "pagePerCnt": "10"})
            items = parse_board(
                source,
                fetch(f"{BASE}/ajaxf/frBoard/bbsViewGalleryList.do", data=fields),
            )
            result.pages += 1
            if not items:
                break
            result.errors.extend(
                {
                    "source": source,
                    "recordKey": item.record_key,
                    "reason": "publication_date_missing",
                }
                for item in items
                if item.published_at is None
            )
            eligible = [
                item
                for item in items
                if item.published_at and cutoff <= item.published_at <= now
            ]
            for item in eligible:
                if item.record_key in seen:
                    continue
                seen.add(item.record_key)
                try:
                    doc = parse_detail(source, item, fetch(item.source_url), now)
                    if doc.published_at and cutoff <= doc.published_at <= now:
                        result.documents.append(doc)
                except (ValueError, OSError, TimeoutError, httpx.HTTPError) as error:
                    result.errors.append(
                        {
                            "source": source,
                            "recordKey": item.record_key,
                            "reason": type(error).__name__,
                        }
                    )
                if len(seen) >= max_records:
                    break
            if len(seen) >= max_records or all(
                item.published_at and item.published_at < cutoff for item in items
            ):
                break
    except (ValueError, OSError, TimeoutError, httpx.HTTPError) as error:
        result.errors.append({"source": source, "reason": type(error).__name__})
    result.status = "partial" if result.errors else "bounded"
    return result
