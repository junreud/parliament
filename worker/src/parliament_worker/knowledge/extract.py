"""Versioned bounded text extraction with Unicode code point mention offsets."""

import json
import re
import subprocess
import sys
from hashlib import sha256
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as dependency_version
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, Tag

from parliament_worker.parsing import license_status, parse_date

EXTRACTOR_VERSION = "knowledge-extractor-v2"
MAX_BYTES = 10_000_000
MAX_PAGES = 30
PDF_TIMEOUT = 60


def digest(value: Any) -> str:
    """Return a stable content digest of JSON-compatible values."""
    return sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _dependency_revision(kind: str) -> str:
    """Include the actually selected extraction runtime in immutable versions."""
    dependency = {"pdf": "pypdf", "html": "beautifulsoup4"}.get(kind)
    if dependency is None:
        return f"python-{sys.version_info.major}.{sys.version_info.minor}"
    try:
        return dependency + ":" + dependency_version(dependency)
    except PackageNotFoundError:
        return dependency + ":unavailable"


def pdf_pages(raw: bytes, *, selected_pages: list[int] | None = None) -> dict[str, Any]:
    """Extract at most 30 PDF pages in a disposable, time-bounded child.

    Args:
        raw: Original PDF bytes, already size checked by the caller.
        selected_pages: Explicit 1-based source pages; at most 30 are processed.

    Returns:
        Original page count, selected page numbers and text without OCR.

    Raises:
        ValueError: PDF is unsupported, malformed or too long.
        subprocess.TimeoutExpired: The child exceeds the 60 second deadline.
    """
    command = [sys.executable, str(Path(__file__).with_name("pdf_child.py"))]
    if selected_pages is not None:
        if (
            not isinstance(selected_pages, list)
            or not selected_pages
            or any(type(page) is not int or page < 1 for page in selected_pages)
            or len(set(selected_pages)) != len(selected_pages)
        ):
            raise ValueError("invalid_page_selection")
        if len(selected_pages) > MAX_PAGES:
            raise ValueError("page_selection_limit")
        command.extend(["--pages", json.dumps(selected_pages)])
    result = subprocess.run(
        command,
        input=raw,
        capture_output=True,
        timeout=PDF_TIMEOUT,
        check=False,
    )
    if result.returncode:
        category = result.stdout.decode("utf-8", errors="replace").strip()
        raise ValueError(
            category
            if category
            in {
                "page_limit",
                "missing_pdf_dependency",
                "encrypted_pdf",
                "page_selection_out_of_range",
                "page_selection_limit",
                "invalid_page_selection",
                "text_limit",
            }
            else "invalid_pdf"
        )
    extraction = json.loads(result.stdout)
    pages = extraction.get("texts") if isinstance(extraction, dict) else None
    if (
        not isinstance(pages, list)
        or len(pages) > MAX_PAGES
        or any(not isinstance(item, str) for item in pages)
        or type(extraction.get("pageCount")) is not int
        or not isinstance(extraction.get("extractedPages"), list)
        or len(extraction["extractedPages"]) != len(pages)
    ):
        raise ValueError("invalid_pdf")
    return extraction


def _mentions(text: str, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Generate identity candidates only; never approve a name match."""
    dictionary: dict[str, set[str]] = {}
    for entity in entities:
        if entity.get("kind") != "person":
            continue
        for name in [entity["name"], *entity.get("aliases", [])]:
            if name:
                dictionary.setdefault(name, set()).add(entity["id"])
    result = []
    for surface, candidates in sorted(dictionary.items()):
        for match in re.finditer(re.escape(surface), text):
            result.append(
                {
                    "id": "mention_"
                    + digest([text, surface, match.start(), match.end()]),
                    "surface": surface,
                    "start": match.start(),
                    "end": match.end(),
                    "candidatePersonIds": sorted(candidates),
                    "personId": None,
                    "decision": "pending",
                }
            )
    return sorted(
        result, key=lambda item: (item["start"], item["end"], item["surface"])
    )


def _html(
    raw: bytes, spec: dict[str, Any]
) -> tuple[list[tuple[str, str]], dict[str, Any]]:
    """Extract selected body text and opt-in image descriptions with locators."""
    soup = BeautifulSoup(raw, "html.parser", from_encoding="utf-8")
    source_license = license_status(soup)
    for node in soup.select("script, style, nav, footer, noscript"):
        node.decompose()
    selector = spec.get("bodySelector", "main, article")
    image_alt_selector = spec.get("imageAltSelector")
    blocks = []
    image_count = 0
    for container_index, container in enumerate(soup.select(selector)):
        selected = container.select("p, li, tr, h1, h2, h3, h4")
        if not selected:
            selected = [container]
        for block_index, node in enumerate(selected):
            if any(
                isinstance(parent, Tag) and parent in selected
                for parent in node.parents
            ):
                continue
            text = node.get_text(" ", strip=True)
            if text:
                blocks.append(
                    (
                        text,
                        f"html:{selector}:container[{container_index}]:block[{block_index}]",
                    )
                )
        if image_alt_selector:
            for image_index, image_node in enumerate(
                container.select(image_alt_selector)
            ):
                if image_node.name != "img":
                    continue
                alt = image_node.get("alt")
                if not isinstance(alt, str) or not alt.strip():
                    continue
                image_count += 1
                if image_count > 50 or len(alt) > 500:
                    raise ValueError("image_alt_limit")
                blocks.append(
                    (
                        alt.strip(),
                        f"html:{selector}:container[{container_index}]:"
                        f"image-alt[{image_index}]",
                    )
                )
    title_node = soup.select_one(spec.get("titleSelector", "title"))
    title = title_node.get_text(" ", strip=True) if title_node else ""
    published_node = (
        soup.select_one(spec["publishedSelector"])
        if spec.get("publishedSelector")
        else None
    )
    date_text = (
        published_node.get("datetime") or published_node.get_text(" ", strip=True)
        if published_node
        else None
    )
    published = parse_date(date_text)
    date_precision = (
        "day"
        if date_text
        and re.search(r"\d{4}[.\-/]\s*\d{1,2}[.\-/]\s*\d{1,2}", date_text)
        and not re.search(r"\d{1,2}:\d{2}", date_text)
        else "second" if published else "unknown"
    )
    return blocks, {
        "title": title,
        "publishedAt": published.isoformat() if published else None,
        "publishedPrecision": date_precision,
        "licenseStatus": source_license,
    }


def _json(raw: bytes, fields: list[str]) -> list[tuple[str, str]]:
    """Extract only explicitly selected dotted field paths from a JSON object."""
    data = json.loads(raw)
    result = []
    for path in fields:
        value = data
        for part in path.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            result.append((str(value), "json:" + path))
    return result


def extract_document(
    raw: bytes,
    spec: dict[str, Any],
    entities: list[dict[str, Any]],
    *,
    extractor_version: str = EXTRACTOR_VERSION,
) -> dict[str, Any]:
    """Extract original text with stable segments and unapproved identity candidates.

    Args:
        raw: Exact response bytes from the supported official URL.
        spec: Operator-reviewed document format and body/field selectors.
        entities: Registered person names and aliases; not identity evidence.
        extractor_version: Explicit processing revision for immutable re-extraction.

    Returns:
        Versioned segments plus explicit extraction and source metadata.
    """
    if len(raw) > MAX_BYTES:
        raise ValueError("document size exceeds limit")
    kind = spec["format"]
    inputs = {
        "rawHash": sha256(raw).hexdigest(),
        "revision": extractor_version,
        "dependencyRevision": _dependency_revision(kind),
        "spec": spec,
        "dictionary": entities,
    }
    metadata: dict[str, Any] = {
        "title": "",
        "publishedAt": None,
        "publishedPrecision": "unknown",
        "licenseStatus": "unknown",
    }
    blocks: list[tuple[str, str]] = []
    status = "available"
    failure_category = None
    page_count = None
    extracted_pages: list[int] = []
    try:
        if kind == "html":
            blocks, metadata = _html(raw, spec)
        elif kind == "json":
            blocks = _json(raw, spec.get("jsonFields", []))
        elif kind == "pdf":
            if not raw.startswith(b"%PDF"):
                raise ValueError("invalid_pdf")
            extraction = (
                pdf_pages(raw, selected_pages=spec["pdfPages"])
                if "pdfPages" in spec
                else pdf_pages(raw)
            )
            page_count = extraction["pageCount"]
            extracted_pages = extraction["extractedPages"]
            blocks = [
                (text, f"pdf:page[{number}]")
                for number, text in zip(extracted_pages, extraction["texts"])
                if text.strip()
            ]
            if len(extracted_pages) < page_count:
                status = "partial"
            if not blocks:
                status = "scan_requires_ocr"
        else:
            status = "unsupported_" + kind
    except subprocess.TimeoutExpired:
        status = "extraction_timeout"
        failure_category = "timeout"
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        status = "extraction_failed"
        category = str(error)
        failure_category = (
            category
            if category
            in {
                "page_limit",
                "missing_pdf_dependency",
                "encrypted_pdf",
                "invalid_pdf",
                "text_limit",
                "invalid_page_selection",
                "page_selection_limit",
                "page_selection_out_of_range",
            }
            else "invalid_pdf" if kind == "pdf" else "invalid_content"
        )
    if not blocks and status == "available":
        status = "metadata_only"
    version = "extract_" + digest(
        inputs
        | {
            "status": status,
            "failureCategory": failure_category,
            "blocks": blocks,
            "metadata": metadata,
            "pageCount": page_count,
            "extractedPages": extracted_pages,
        }
    )
    segments = []
    for index, (text, locator) in enumerate(blocks):
        segment_id = "segment_" + digest([spec["id"], version, index, locator, text])
        mentions = _mentions(text, entities)
        for mention in mentions:
            mention["id"] = "mention_" + digest(
                [segment_id, mention["start"], mention["end"], mention["surface"]]
            )
        segments.append(
            {"id": segment_id, "text": text, "locator": locator, "mentions": mentions}
        )
    return metadata | {
        "extractionVersion": version,
        "bodyStatus": status,
        "failureCategory": failure_category,
        "pageCount": page_count,
        "extractedPages": extracted_pages,
        "segments": segments,
    }
