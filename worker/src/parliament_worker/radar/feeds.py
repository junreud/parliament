"""Bounded publisher RSS and a distinct public search-interest signal."""

import ipaddress
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import urljoin, urlsplit

import httpx

from parliament_worker.http import resolve_public
from parliament_worker.radar.models import Article, canonical_url


@dataclass(frozen=True)
class Feed:
    """Operator-approved discovery feed; attribution does not come from input XML."""

    publisher: str
    url: str
    article_hosts: tuple[str, ...]


SOURCES = (
    Feed(
        "연합뉴스",
        "https://www.yna.co.kr/rss/politics.xml",
        ("www.yna.co.kr", "yna.co.kr"),
    ),
    Feed("동아일보", "https://rss.donga.com/politics.xml", ("www.donga.com",)),
    Feed("한겨레", "https://www.hani.co.kr/rss/politics/", ("www.hani.co.kr",)),
    Feed(
        "경향신문",
        "https://www.khan.co.kr/rss/rssdata/politic_news.xml",
        ("www.khan.co.kr",),
    ),
)
TRENDS_URL = "https://trends.google.com/trending/rss?geo=KR"
FEED_HOSTS = frozenset(urlsplit(s.url).hostname for s in SOURCES) | {
    "trends.google.com"
}


def clean(value: str | None) -> str:
    """Strip markup without rendering remote HTML."""
    return re.sub(r"\s+", " ", re.sub("<[^>]*>", "", unescape(value or ""))).strip()[
        :300
    ]


def date(value: str | None) -> datetime | None:
    """Parse an explicit RFC/ISO timestamp; never invent an observation date."""
    if not value:
        return None
    try:
        result = parsedate_to_datetime(value)
    except (ValueError, TypeError):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return result.astimezone(timezone.utc) if result.tzinfo else None


def xml(raw: bytes) -> ET.Element:
    """Reject DTD/entity declarations and excessive input before XML parsing."""
    if len(raw) > 2_000_000 or re.search(rb"<!\s*(DOCTYPE|ENTITY)", raw, re.I):
        raise ValueError("unsupported feed XML")
    try:
        return ET.fromstring(raw)
    except ET.ParseError as error:
        raise ValueError("malformed feed XML") from error


def parse_feed(raw: bytes, source: Feed, now: datetime) -> list[Article]:
    """Read up to 200 headlines within 72 hours with explicit publisher timestamps."""
    root = xml(raw)
    if root.tag != "rss" or root.find("channel") is None:
        raise ValueError("not an RSS feed")
    items: dict[str, Article] = {}
    for item in root.findall("./channel/item")[:200]:
        title = clean(item.findtext("title"))
        published = date(
            item.findtext("pubDate")
            or item.findtext("{http://purl.org/dc/elements/1.1/}date")
        )
        if (
            not title
            or not published
            or not now - timedelta(hours=72) <= published <= now + timedelta(minutes=5)
        ):
            continue
        try:
            url = canonical_url(item.findtext("link") or "")
        except ValueError:
            continue
        if urlsplit(url).hostname not in source.article_hosts:
            continue
        article = Article(title, url, source.publisher, published)
        items[article.id] = article
    return list(items.values())


def parse_trends(raw: bytes, now: datetime) -> list[dict]:
    """Keep search-interest metadata separate; it does not validate any news claim."""
    result = []
    for item in xml(raw).findall("./channel/item")[:50]:
        published = date(item.findtext("pubDate"))
        keyword = clean(item.findtext("title"))
        if (
            keyword
            and published
            and now - timedelta(hours=48) <= published <= now + timedelta(minutes=5)
        ):
            result.append(
                {
                    "keyword": keyword,
                    "traffic": clean(
                        item.findtext(
                            "{https://trends.google.com/trending/rss}approx_traffic"
                        )
                    ),
                    "publishedAt": published.isoformat(),
                }
            )
    return result


class NewsFetcher:
    """Fetch only fixed public RSS hosts with bounded redirects, bytes and duration."""

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        resolver: Callable[[str], list[str]] = resolve_public,
        max_bytes: int = 2_000_000,
    ) -> None:
        self.client = client or httpx.Client(
            timeout=12,
            follow_redirects=False,
            headers={"User-Agent": "ParliamentIssueRadar/1.0 (RSS metadata only)"},
        )
        self.resolver = resolver
        self.max_bytes = max_bytes

    def __call__(self, url: str) -> bytes:
        """Read a public feed; validate every redirect and reject private DNS answers."""
        deadline = time.monotonic() + 30
        for _ in range(4):
            parts = urlsplit(url)
            if (
                parts.scheme != "https"
                or parts.hostname not in FEED_HOSTS
                or parts.username
                or parts.password
                or parts.port not in (None, 443)
                or parts.fragment
            ):
                raise ValueError("unsupported feed URL")
            addresses = self.resolver(parts.hostname)
            if not addresses or any(
                not ipaddress.ip_address(ip).is_global for ip in addresses
            ):
                raise ValueError("private feed address")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("feed deadline exceeded")
            with self.client.stream(
                "GET",
                url,
                timeout=min(12, remaining),
                headers={"Accept-Encoding": "identity"},
            ) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers.get("location", ""))
                    continue
                response.raise_for_status()
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > self.max_bytes:
                        raise ValueError("feed too large")
                    if time.monotonic() > deadline:
                        raise TimeoutError("feed deadline exceeded")
                return bytes(raw)
        raise ValueError("too many feed redirects")

    def close(self) -> None:
        """Release owned connections."""
        self.client.close()
