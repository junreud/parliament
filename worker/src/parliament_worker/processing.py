"""Source-grounded structural events; explanations remain in a review queue."""

import json
from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime
from typing import Any

from parliament_worker.activity import version_activity
from parliament_worker.content import document_body_status
from parliament_worker.http import validate_official_url
from parliament_worker.models import ProcessingResult, SourceDocument
from parliament_worker.parsing import PARSER_VERSION
from parliament_worker.storage import LocalRawStore


def build_event(document: SourceDocument, *, corrected: bool = False) -> dict[str, Any]:
    """Build the backend activity contract without generated explanations.

    Args:
        document: An official article with a specific original version.
        corrected: Whether earlier versions of this source identity exist.

    Returns:
        A structural announcement with null summary and exact-version evidence.
    """
    validate_official_url(document.source_url)
    if document.published_at is None:
        raise ValueError("actual publication date required")
    if not document.title or not document.raw:
        raise ValueError("title and raw version required")
    body_status = document_body_status(document)
    metadata_only = body_status != "available"
    if metadata_only and not document.title_locator:
        raise ValueError("original headline locator required for metadata-only event")
    coverage = (
        f"공개 발표 원문: {document.agency or document.source_key}. "
        "공식 발표 기록이며 시행·성과 또는 독립적으로 검증된 사실을 뜻하지 않습니다. "
        "발표에 등장하는 사람과 실제 발생 시각은 원문 근거가 있을 때만 표시합니다."
    )
    if metadata_only:
        limitation = (
            "게시물에는 보도자료를 옮겨 실었다는 안내만 있어 발표 본문을 확인하지 못했습니다. "
            if body_status == "disclaimer_only"
            else "게시물에서 발표 본문을 확인하지 못했습니다. "
        )
        coverage = (
            f"공식 발표 제목과 게시 정보만 확인했습니다: {document.agency or document.source_key}. "
            + limitation
            + "발표 상세 내용과 첨부 문서의 본문을 확인하지 못했습니다. "
            "실제 행동·시행·성과는 확인되지 않았습니다. 제목만으로 발표 전체 내용을 검증한 것은 아닙니다."
        )
    if document.attachments:
        document_types = {
            "unsupported_hwp": "한글(HWP)",
            "unsupported_hwpx": "한글(HWPX)",
            "optional_pdf": "PDF",
        }
        labels = dict.fromkeys(
            document_types.get(item.status, "기타 문서")
            for item in document.attachments
        )
        coverage += " 첨부 문서 유형: " + ", ".join(labels) + " (내용 미확인)."
    payload = {
        "id": f"gov_{document.identity}",
        "type": "announcement",
        "title": document.title[:500],
        "summary": None,
        "stage": "announced",
        "personIds": [],
        "topics": [],
        "billId": None,
        "occurredAt": (
            document.occurred_at.isoformat() if document.occurred_at else None
        ),
        "publishedAt": document.published_at.isoformat(),
        "collectedAt": document.collected_at.isoformat(),
        "sourceUrl": document.source_url,
        "evidence": [
            {
                "id": f"ev_{document.identity}",
                "sourceUrl": document.source_url,
                "excerpt": (
                    document.title[:5000] if metadata_only else document.body[:5000]
                ),
                "locator": (
                    document.title_locator if metadata_only else document.locator
                ),
                "sourceVersion": document.payload_hash,
            }
        ],
        "votes": [],
        "coverage": coverage[:2000],
        "corrected": corrected,
    }
    return version_activity(payload, PARSER_VERSION)


def process_documents(
    documents: Iterable[SourceDocument], *, store: LocalRawStore | None = None
) -> ProcessingResult:
    """Preserve versions and segregate material unsafe for automatic publication.

    Reuse restrictions and missing publication dates remain visible. Cross-source
    equal titles do not merge. No filesystem or external writes happen by default.
    """
    result = ProcessingResult()
    seen: set[tuple[str, str]] = set()
    for document in documents:
        key = (document.identity, document.payload_hash)
        if key in seen:
            continue
        seen.add(key)
        if store:
            raw_path = store.save(document)
            first_observation = json.loads(raw_path.with_suffix(".json").read_text())
            document = replace(
                document,
                collected_at=datetime.fromisoformat(first_observation["observedAt"]),
            )
        reason = None
        if document.published_at is None:
            reason = "publication_date_missing"
        elif document.license_status == "restricted":
            reason = "license_restricted"
        elif document.license_status != "allowed":
            reason = "license_unverified"
        elif not document.body and not document.title_locator:
            reason = "source_body_missing"
        if reason:
            result.review_queue.append(
                {
                    "sourceKey": document.source_key,
                    "recordKey": document.record_key,
                    "sourceUrl": document.source_url,
                    "sourceVersion": document.payload_hash,
                    "agency": document.agency,
                    "reason": reason,
                    "status": "blocked",
                    "publishedAt": (
                        document.published_at.isoformat()
                        if document.published_at
                        else None
                    ),
                    "occurredAt": (
                        document.occurred_at.isoformat()
                        if document.occurred_at
                        else None
                    ),
                }
            )
            continue
        corrected = bool(
            store and store.version_number(document.identity, document.payload_hash) > 1
        )
        result.events.append(build_event(document, corrected=corrected))
        body_status = document_body_status(document)
        if body_status != "available":
            result.review_queue.append(
                {
                    "sourceKey": document.source_key,
                    "recordKey": document.record_key,
                    "sourceUrl": document.source_url,
                    "sourceVersion": document.payload_hash,
                    "agency": document.agency,
                    "reason": f"source_body_{body_status}",
                    "scope": "summary",
                    "status": "blocked",
                    "publishedAt": document.published_at.isoformat(),
                    "occurredAt": (
                        document.occurred_at.isoformat()
                        if document.occurred_at
                        else None
                    ),
                }
            )
    return result
