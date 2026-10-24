"""Bounded law API access; authentication never becomes document provenance."""

import json
import logging
import os
import re
import ssl
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import httpx

BASE_URL = "https://www.law.go.kr/DRF/"


class LawError(ValueError):
    """Expose only fixed failure categories, without request URLs or API messages."""


class _AuthFilter(logging.Filter):
    """Hide the OC query value in HTTPX's ordinary request log."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = re.sub(
            r"([?&]OC=)[^&\s\"\]]+", r"\1[REDACTED]", record.getMessage(), flags=re.I
        )
        record.args = ()
        return True


_HTTP_FILTER = _AuthFilter()
logging.getLogger("httpx").addFilter(_HTTP_FILTER)


def law_date(value: Any) -> str | None:
    """Convert an official calendar date, preserving explicit unknown values."""
    if value in (None, "", "00000000", 0):
        return None
    text = str(value)
    if not re.fullmatch(r"[0-9]{8}", text):
        raise LawError("invalid_law_date")
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:])).isoformat()
    except ValueError:
        raise LawError("invalid_law_date") from None


def _identifier(value: Any) -> str:
    text = str(value or "")
    if not re.fullmatch(r"[0-9]{1,16}", text):
        raise LawError("invalid_law_identity")
    return text


@dataclass(frozen=True)
class LawRecord:
    """An explicitly selected law ID and official version, with separate dates."""

    law_id: str
    mst: str
    title: str
    promulgated: str | None
    effective: str | None
    number: str


@dataclass(frozen=True)
class LawPage:
    """A validated search page containing no credential-bearing source links."""

    records: list[LawRecord]
    total: int


class LawClient:
    """Read only the fixed official HTTPS API with no authentication redirects."""

    def __init__(
        self, oc: str, *, client: httpx.Client | None = None, max_bytes: int = 5_000_000
    ) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", oc or ""):
            raise LawError("law_oc_required_or_invalid")
        if not 1 <= max_bytes <= 10_000_000:
            raise LawError("invalid_response_limit")
        self._oc = oc
        self.max_bytes = max_bytes
        self.client = client or httpx.Client(
            follow_redirects=False,
            timeout=20.0,
            headers={"User-Agent": "ParliamentDataPlatform/1.0"},
        )

    @classmethod
    def from_env(cls) -> "LawClient":
        """Read OC and optional additive CA trust from the server environment."""
        oc = os.environ.get("PARLIAMENT_LAW_OC", "")
        ca = os.environ.get("PARLIAMENT_LAW_CA_CERTIFICATE")
        client = None
        if ca:
            if not Path(ca).is_file():
                raise LawError("law_ca_missing")
            context = ssl.create_default_context()
            context.load_verify_locations(ca)
            client = httpx.Client(
                verify=context,
                follow_redirects=False,
                timeout=20.0,
                headers={"User-Agent": "ParliamentDataPlatform/1.0"},
            )
        return cls(oc, client=client)

    def _read(self, path: str, params: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
        """Bound bytes/time before parsing and suppress secret-bearing errors."""
        deadline = time.monotonic() + 40
        try:
            with self.client.stream(
                "GET",
                BASE_URL + path,
                params={"OC": self._oc, "target": "law", "type": "JSON", **params},
                follow_redirects=False,
                timeout=20.0,
            ) as response:
                if response.status_code != 200:
                    raise LawError("law_http_error")
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise LawError("law_response_limit")
                    if time.monotonic() > deadline:
                        raise LawError("law_response_timeout")
                    chunks.append(chunk)
                raw = b"".join(chunks)
            data = json.loads(raw)
            if not isinstance(data, dict) or "result" in data or "msg" in data:
                raise LawError("law_auth_or_api_error")
            return data, raw
        except (httpx.HTTPError, ValueError, TypeError) as error:
            if isinstance(error, LawError):
                raise
            raise LawError("law_transport_or_json_error") from None

    def search(self, query: str, *, page: int, page_size: int) -> LawPage:
        """Search a bounded name page; discard OC-bearing links from the response."""
        if (
            not query.strip()
            or len(query) > 200
            or not 1 <= page <= 5
            or not 1 <= page_size <= 20
        ):
            raise LawError("invalid_search_bounds")
        data, _ = self._read(
            "lawSearch.do", {"query": query, "page": page, "display": page_size}
        )
        block = data.get("LawSearch")
        if not isinstance(block, dict):
            raise LawError("invalid_law_search")
        try:
            total = int(block["totalCnt"])
        except (KeyError, ValueError, TypeError):
            raise LawError("invalid_law_count") from None
        rows = block.get("law", [])
        if isinstance(rows, dict):
            rows = [rows]
        if (
            total < 0
            or not isinstance(rows, list)
            or len(rows) > page_size
            or (not rows and (page - 1) * page_size < total)
        ):
            raise LawError("invalid_law_page")
        records = []
        for row in rows:
            if not isinstance(row, dict):
                raise LawError("invalid_law_row")
            title = row.get("법령명한글")
            if (
                not isinstance(title, str)
                or not title.strip()
                or len(title) > 500
                or self._oc in title
            ):
                raise LawError("invalid_law_title")
            records.append(
                LawRecord(
                    _identifier(row.get("법령ID")),
                    _identifier(row.get("법령일련번호")),
                    title,
                    law_date(row.get("공포일자")),
                    law_date(row.get("시행일자")),
                    str(row.get("공포번호") or ""),
                )
            )
        return LawPage(records, total)

    def detail(self, record: LawRecord) -> bytes:
        """Fetch the listed MST and verify metadata before preserving exact bytes."""
        data, raw = self._read("lawService.do", {"MST": record.mst})
        if self._oc.encode() in raw:
            raise LawError("credential_in_law_detail")
        law = data.get("법령")
        basic = law.get("기본정보") if isinstance(law, dict) else None
        if not isinstance(basic, dict):
            raise LawError("invalid_law_detail")
        if (
            _identifier(basic.get("법령ID")) != record.law_id
            or basic.get("법령명_한글") != record.title
            or law_date(basic.get("공포일자")) != record.promulgated
            or law_date(basic.get("시행일자")) != record.effective
            or str(basic.get("공포번호") or "") != record.number
        ):
            raise LawError("law_version_mismatch")
        return raw

    def close(self) -> None:
        """Release HTTP resources without exposing the OC."""
        self.client.close()
