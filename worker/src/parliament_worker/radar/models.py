"""Small immutable news observations and safe publisher URLs."""

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

PUBLISHER_HOSTS = frozenset(
    {"www.yna.co.kr", "yna.co.kr", "www.donga.com", "www.hani.co.kr", "www.khan.co.kr"}
)


def canonical_url(value: str) -> str:
    """Preserve article identity while removing tracking parameters and fragments."""
    parts = urlsplit(value.strip())
    if (
        parts.scheme != "https"
        or parts.hostname not in PUBLISHER_HOSTS
        or parts.username
        or parts.password
        or parts.port not in (None, 443)
        or len(value) > 2048
    ):
        raise ValueError("unsupported publisher URL")
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query)
        if not k.startswith("utm_") and k not in {"fbclid", "gclid"}
    ]
    return urlunsplit(("https", parts.netloc.lower(), parts.path, urlencode(query), ""))


def iso(value: datetime) -> str:
    """Serialize an aware time in UTC."""
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Article:
    """A publisher headline; it is not an independently verified factual claim."""

    title: str
    url: str
    publisher: str
    published_at: datetime

    @property
    def id(self) -> str:
        """Stable identity for the canonical publisher URL."""
        return hashlib.sha256(self.url.encode()).hexdigest()[:20]

    def public(self) -> dict:
        """Export only attributed metadata, never full article bodies/images."""
        return {
            "title": self.title,
            "url": self.url,
            "publisher": self.publisher,
            "publishedAt": iso(self.published_at),
        }
