"""Immutable source records retain original identity and independent timestamps."""

from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from typing import Any
from zoneinfo import ZoneInfo

SEOUL = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class Attachment:
    """A discovered attachment; unsupported formats are never silently discarded."""

    source_url: str
    name: str
    status: str


@dataclass(frozen=True)
class Listing:
    """An official source identifier and publication hint from a list row."""

    record_key: str
    source_url: str
    title: str
    published_at: datetime | None
    agency: str = ""


@dataclass(frozen=True)
class SourceDocument:
    """A fetched source version without inferred dates or person identity.

    Attributes:
        published_at: Actual source registration/publication date, if available.
        occurred_at: Explicit occurrence date only, never copied from publication.
        raw: Original response bytes used for the content-addressed version.
        agency: Issuing organization; it does not imply a particular minister acted.
        license_status: Allowed, restricted, or unknown reuse evidence.
    """

    source_key: str
    record_key: str
    source_url: str
    title: str
    body: str
    published_at: datetime | None
    collected_at: datetime
    locator: str
    agency: str = ""
    raw: bytes = b""
    occurred_at: datetime | None = None
    attachments: tuple[Attachment, ...] = ()
    license_status: str = "unknown"
    body_status: str = "available"
    title_locator: str = ""

    @property
    def payload_hash(self) -> str:
        """Return a digest of the immutable original response bytes."""
        return sha256(self.raw).hexdigest()

    @property
    def identity(self) -> str:
        """Return source identity independently of title or version hash."""
        return sha256(f"{self.source_key}:{self.record_key}".encode()).hexdigest()


@dataclass
class CollectionResult:
    """Visible partial failures and bounded collection coverage."""

    documents: list[SourceDocument] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    status: str = "bounded"
    pages: int = 0


@dataclass
class ProcessingResult:
    """Structural public candidates and items blocked from publication."""

    events: list[dict[str, Any]] = field(default_factory=list)
    review_queue: list[dict[str, Any]] = field(default_factory=list)
