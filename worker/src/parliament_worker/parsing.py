"""Conservative date, text and reuse metadata parsing shared by connectors."""

import json
import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from parliament_worker.http import validate_official_url
from parliament_worker.models import SEOUL, Attachment

PARSER_VERSION = "official-html-v2"


def clean_text(value: str) -> str:
    """Strip HTML markup without losing quoted punctuation or number signs."""
    return " ".join(
        BeautifulSoup(value, "html.parser").get_text(" ", strip=True).split()
    )


def parse_date(value: str | None) -> datetime | None:
    """Parse explicit dates; missing dates never become collection time."""
    if not value:
        return None
    candidate = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        match = re.search(r"(\d{4})[.\-/]\s*(\d{1,2})[.\-/]\s*(\d{1,2})", value)
        if match is None:
            return None
        try:
            parsed = datetime(*(int(x) for x in match.groups()))
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=SEOUL)


def json_article(soup: BeautifulSoup) -> dict:
    """Return official structured article metadata where present."""
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(node.get_text())
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict) and value.get("@type") in (
            "NewsArticle",
            "Article",
            "Report",
        ):
            return value
    return {}


def license_status(soup: BeautifulSoup) -> str:
    """Detect visible noncommercial/no-derivatives notices before publishing."""
    text = soup.get_text(" ", strip=True)
    if re.search(r"제\s*[234]\s*유형|비상업|변형.*금지", text):
        return "restricted"
    images = " ".join(str(n) for n in soup.select('img[src*="open"], img[src*="kogl"]'))
    if re.search(r"type[234]|mark[234]", images):
        return "restricted"
    if re.search(r"제\s*1\s*유형|제\s*0\s*유형", text) or re.search(
        r"type1|mark1", images
    ):
        return "allowed"
    return "unknown"


def discover_attachments(
    soup: BeautifulSoup, source_url: str
) -> tuple[Attachment, ...]:
    """Keep supported and unsupported attachment links visible without fetching."""
    found: dict[str, Attachment] = {}
    for node in soup.select("a[href]"):
        name = node.get_text(" ", strip=True)
        match = re.search(r"\.(hwp|hwpx|pdf)\b", name, re.IGNORECASE)
        if match is None:
            continue
        url = urljoin(source_url, str(node["href"]))
        try:
            validate_official_url(url)
        except ValueError:
            continue
        kind = match[1].lower()
        status = "optional_pdf" if kind == "pdf" else f"unsupported_{kind}"
        found[url] = Attachment(url, name, status)
    return tuple(found.values())
