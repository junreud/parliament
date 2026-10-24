"""Official HTML connectors for the PM office and ministry press releases."""

from collections.abc import Callable
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from parliament_worker.content import classify_body
from parliament_worker.http import validate_official_url
from parliament_worker.models import CollectionResult, Listing, SourceDocument
from parliament_worker.parsing import (
    discover_attachments,
    json_article,
    license_status,
    parse_date,
)

SOURCES = {
    "korea": "https://www.korea.kr/briefing/pressReleaseList.do",
    "opm": "https://www.opm.go.kr/opm/news/press-release.do",
    "president-briefings": "https://www.president.go.kr/briefings",
    "president-speeches": "https://www.president.go.kr/speeches",
    "president-schedule": "https://www.president.go.kr/schedule",
}


def parse_listing(source: str, raw: bytes) -> list[Listing]:
    """Read official source IDs, row-level agency and registration dates.

    Args:
        source: korea or opm; President data uses its public AJAX adapter.
        raw: Original HTML response bytes.

    Returns:
        Listings whose IDs come from newsId or articleNo rather than title hashes.

    Raises:
        ValueError: Official list selectors are absent, signalling parser drift.
    """
    soup = BeautifulSoup(raw, "html.parser")
    selector = (
        'a[href*="pressReleaseView.do?newsId="]'
        if source == "korea"
        else "a.c-board-title"
    )
    nodes = soup.select(selector)
    if not nodes:
        raise ValueError("official listing structure missing")
    items: dict[str, Listing] = {}
    for node in nodes:
        href = str(node.get("href", ""))
        params = parse_qs(urlsplit(href).query)
        key = params.get("newsId" if source == "korea" else "articleNo", [""])[0]
        if not key.isdigit():
            continue
        if source == "korea":
            title_node = node.select_one("strong")
            if title_node is None:
                continue  # Ignore sidebar links to the same article.
            source_fields = node.select(".source span")
            published = parse_date(
                source_fields[0].get_text() if source_fields else None
            )
            agency = (
                source_fields[1].get_text(strip=True) if len(source_fields) > 1 else ""
            )
            title = title_node.get_text(" ", strip=True)
            url = f"https://www.korea.kr/briefing/pressReleaseView.do?newsId={key}"
        else:
            row = node.find_parent("tr")
            cells = row.find_all("td", recursive=False) if row else []
            published = parse_date(cells[3].get_text() if len(cells) > 3 else None)
            agency = (
                cells[2].get_text(strip=True)
                if len(cells) > 2
                else "국무조정실·국무총리비서실"
            )
            title = node.get_text(" ", strip=True)
            url = f"{SOURCES['opm']}?mode=view&articleNo={key}"
        validate_official_url(url)
        items[key] = Listing(key, url, title, published, agency)
    if not items:
        raise ValueError("official listing structure has no usable records")
    return list(items.values())


def parse_detail(
    source: str, item: Listing, raw: bytes, collected: datetime
) -> SourceDocument:
    """Extract article body and actual publication metadata from official HTML."""
    soup = BeautifulSoup(raw, "html.parser")
    if source.startswith("president-"):
        title_selector = ".lineList_v .txtL"
        date_selector = ".lineList_v .txtInfo .date .data"
        body_selector = ".lineList_v .view_txt"
    elif source == "opm":
        title_selector = ".board-view-title-wrap h4"
        date_selector = ".board-view-title-wrap"
        body_selector = ".board-view-txt"
    else:
        title_selector = ".view_title h1"
        date_selector = ".article_head .info"
        body_selector = ".view_cont"
    title_node = soup.select_one(title_selector)
    body_node = soup.select_one(body_selector)
    if title_node is None or (body_node is None and source != "korea"):
        raise ValueError("official article structure missing")
    metadata = json_article(soup)
    date_node = soup.select_one(date_selector)
    publication = parse_date(str(metadata.get("datePublished", "")))
    publication = (
        publication
        or parse_date(date_node.get_text() if date_node else None)
        or item.published_at
    )
    if (
        not metadata.get("datePublished")
        and publication
        and item.published_at
        and publication.date() == item.published_at.date()
    ):
        publication = item.published_at
    author = metadata.get("author", {})
    agency = str(author.get("name", "")) if isinstance(author, dict) else ""
    return SourceDocument(
        source,
        item.record_key,
        item.source_url,
        title_node.get_text(" ", strip=True),
        body_node.get_text(" ", strip=True) if body_node else "",
        publication,
        collected,
        body_selector,
        agency=agency or item.agency or "대통령실",
        raw=raw,
        attachments=discover_attachments(soup, item.source_url),
        license_status=license_status(soup),
        body_status=classify_body(
            body_node.get_text(" ", strip=True) if body_node else ""
        ),
        title_locator=title_selector,
    )


def collect(
    source: str,
    fetch: Callable[..., bytes],
    now: datetime,
    *,
    max_pages: int = 2,
    days: int = 90,
    max_records: int = 30,
) -> CollectionResult:
    """Collect only a recent bounded window and report every partial failure."""
    if (
        source not in SOURCES
        or not 1 <= max_pages <= 10
        or not 1 <= days <= 90
        or not 1 <= max_records <= 100
    ):
        raise ValueError("unsupported source or collection limits")
    if source.startswith("president-"):
        from parliament_worker.president import collect_president

        return collect_president(
            source, fetch, now, max_pages=max_pages, days=days, max_records=max_records
        )
    result = CollectionResult()
    cutoff = now - timedelta(days=days)
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        params = (
            {"pageIndex": page}
            if source == "korea"
            else {"article.offset": (page - 1) * 10, "articleLimit": 10}
        )
        url = f"{SOURCES[source]}?{urlencode(params)}"
        try:
            items = parse_listing(source, fetch(url))
            result.pages += 1
        except (ValueError, OSError, TimeoutError, httpx.HTTPError) as error:
            result.errors.append({"source": source, "reason": type(error).__name__})
            break
        old = True
        for item in items:
            if item.published_at is None:
                result.errors.append(
                    {
                        "source": source,
                        "recordKey": item.record_key,
                        "reason": "publication_date_missing",
                    }
                )
            if item.published_at is None or item.published_at >= cutoff:
                old = False
            if (
                item.record_key in seen
                or item.published_at is None
                or item.published_at < cutoff
                or item.published_at > now
            ):
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
        if old or len(seen) >= max_records:
            break
    result.status = "partial" if result.errors else "bounded"
    return result
