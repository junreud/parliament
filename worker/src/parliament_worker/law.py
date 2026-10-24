"""Version-pinned law originals and unapproved evidence batches."""

import json
import re
from datetime import datetime
from typing import Any

from parliament_worker.knowledge.extract import digest
from parliament_worker.knowledge.files import private_read, private_write
from parliament_worker.knowledge.pipeline import ID_PATTERN
from parliament_worker.knowledge.review import validate_batch
from parliament_worker.knowledge.store import PilotStore
from parliament_worker.law_client import LawClient, LawError, LawRecord
from parliament_worker.models import SEOUL


def _spec(record: LawRecord) -> dict[str, Any]:
    """Keep stable legal identity separate from collection time and authentication."""
    return {
        "id": f"law_{record.law_id}_{record.mst}",
        "sourceKey": "law",
        "recordKey": f"{record.law_id}:{record.mst}",
        "sourceUrl": f"https://www.law.go.kr/DRF/lawService.do?target=law&MST={record.mst}&type=JSON",
        "format": "json",
        "title": record.title,
        "lawId": record.law_id,
        "mst": record.mst,
        "promulgatedDate": record.promulgated,
        "effectiveDate": record.effective,
    }


def collect_laws(
    client: LawClient,
    query: str,
    *,
    store: PilotStore | None,
    job_id: str,
    collected_at: datetime,
    max_records: int = 10,
    max_pages: int = 1,
) -> dict[str, Any]:
    """Collect selected versions with explicit bounds and replay-safe observations.

    Args:
        client: Credential-protected official API client.
        query: Operator-selected law name; no nationwide implicit crawl.
        store: Explicit private storage, or None for a read-only preview.
        job_id: Reuse only to replay the same collection attempt.
        collected_at: Actual observation timestamp, never a law date.
        max_records: Maximum 1..20 selected versions per invocation.
        max_pages: Maximum 1..5 search pages per invocation.

    Returns:
        Safe counts, selected metadata and observations without authentication.
    """
    if (
        not ID_PATTERN.fullmatch(job_id)
        or collected_at.tzinfo is None
        or not 1 <= max_records <= 20
        or not 1 <= max_pages <= 5
    ):
        raise ValueError("invalid_law_collection_bounds")
    selection = {"query": query, "maxRecords": max_records, "maxPages": max_pages}
    report_path = store.root / "runs" / f"{job_id}.json" if store else None
    if report_path and report_path.exists():
        previous = json.loads(private_read(report_path, root=store.root))
        if previous["selection"] != selection:
            raise ValueError("law_job_replay_selection_conflict")
        return previous
    observations, errors, seen = [], [], set()
    total, scanned, pages = None, 0, 0
    for page_number in range(1, max_pages + 1):
        if len(observations) >= max_records:
            break
        try:
            page = client.search(
                query, page=page_number, page_size=min(max_records, 20)
            )
        except LawError:
            errors.append("law_search_failed")
            break
        pages += 1
        if total is not None and total != page.total:
            errors.append("law_search_changed_during_scan")
        total = page.total
        for record in page.records:
            if len(observations) >= max_records:
                break
            spec = _spec(record)
            if spec["id"] in seen:
                errors.append("duplicate_law_search_record")
                continue
            seen.add(spec["id"])
            scanned += 1
            prior = store.observations(spec["id"], job_id=job_id) if store else []
            if prior:
                if prior[0]["spec"] != spec:
                    raise ValueError("law_job_replay_identity_conflict")
                observations.extend(prior)
                continue
            try:
                raw = client.detail(record)
                observations.append(
                    store.observe(spec, raw, job_id, collected_at)
                    if store
                    else {"status": "success", "spec": spec}
                )
            except LawError as error:
                category = type(error).__name__
                if store:
                    if store.observations(spec["id"], job_id=job_id):
                        raise
                    store.failure(spec, job_id, collected_at, category)
                    observations.extend(store.observations(spec["id"], job_id=job_id))
                else:
                    observations.append(
                        {"status": "failed", "spec": spec, "errorCategory": category}
                    )
        if scanned >= total:
            break
    failures = sum(item["status"] == "failed" for item in observations)
    report = {
        "selection": selection,
        "jobId": job_id,
        "totalCount": total,
        "pages": pages,
        "successes": len(observations) - failures,
        "failures": failures + len(errors),
        "errors": errors,
        "complete": total is not None
        and scanned >= total
        and not failures
        and not errors,
        "observations": observations,
    }
    if report_path:
        private_write(
            report_path,
            json.dumps(report, ensure_ascii=False, sort_keys=True).encode(),
            root=store.root,
        )
    return report


def _passages(
    value: Any, path: str, *, metadata: bool = False, field: str = ""
) -> list[tuple[str, str]]:
    """Traverse JSON arrays while retaining the exact path of each original string."""
    if isinstance(value, dict):
        return [
            item
            for key, child in value.items()
            for item in _passages(child, path + "." + key, metadata=metadata, field=key)
        ]
    if isinstance(value, list):
        return [
            item
            for index, child in enumerate(value)
            for item in _passages(
                child, f"{path}[{index}]", metadata=metadata, field=field
            )
        ]
    fields = {"법령ID", "법령명_한글", "공포일자", "공포번호", "시행일자"}
    selected = (
        field in fields or (field == "content" and "소관부처" in path)
        if metadata
        else field.endswith("내용")
    )
    if selected and isinstance(value, (str, int)) and str(value).strip():
        return [(str(value), "json:" + path)]
    return []


def prepare_law_batch(
    report: dict[str, Any], store: PilotStore, *, issue_id: str
) -> dict[str, Any]:
    """Prepare only source-grounded documents and citations; no public activities."""
    if not ID_PATTERN.fullmatch(issue_id):
        raise ValueError("invalid_law_issue_id")
    documents, evidence = [], []
    successful = sum(item["status"] == "success" for item in report["observations"])
    segment_limit = min(500, 2000 // max(successful, 1))
    for observation in report["observations"]:
        if observation["status"] != "success":
            continue
        spec = observation["spec"]
        law = json.loads(store.read_raw(observation))["법령"]
        metadata = _passages(law["기본정보"], "법령.기본정보", metadata=True)
        body = [
            item
            for section in ("조문", "부칙", "개정문", "제개정이유")
            for item in _passages(law.get(section, {}), "법령." + section)
        ]
        selected = (metadata + body)[:segment_limit] if body else []
        partial = len(metadata + body) > segment_limit or any(
            len(text) > 100000 for text, _ in selected
        )
        blocks = [(text[:100000], locator) for text, locator in selected]
        revision = "law_extract_" + digest(
            ["law-json-v1", observation["version"], blocks]
        )
        segments = [
            {
                "id": "segment_" + digest([spec["id"], revision, locator, text]),
                "text": text,
                "locator": locator,
                "mentions": [],
            }
            for text, locator in blocks
        ]
        extraction = {
            "extractionVersion": revision,
            "segments": segments,
            "bodyStatus": (
                "partial" if partial else "available" if body else "unavailable"
            ),
        }
        store.save_extraction(spec["id"], extraction)
        promulgated = spec["promulgatedDate"]
        document = {
            "id": spec["id"],
            "version": observation["version"],
            "sourceKey": spec["sourceKey"],
            "recordKey": spec["recordKey"],
            "sourceUrl": spec["sourceUrl"],
            "title": spec["title"],
            "format": "json",
            "licenseStatus": "unknown",
            "publishedAt": (
                datetime.fromisoformat(promulgated).replace(tzinfo=SEOUL).isoformat()
                if promulgated
                else None
            ),
            "datePrecision": "date" if promulgated else "unknown",
            **store.version_metadata(observation),
            **extraction,
            "rawStorageKey": observation["rawStorageKey"],
            "observationId": observation["observationId"],
            "observedAt": observation["observedAt"],
        }
        documents.append(document)
        evidence.extend(
            {
                "id": "evidence_" + digest([segment["id"], 0, len(segment["text"])]),
                "documentId": spec["id"],
                "documentVersion": observation["version"],
                "extractionVersion": revision,
                "segmentId": segment["id"],
                "start": 0,
                "end": len(segment["text"]),
            }
            for segment in segments
        )
    content = {
        "issueId": issue_id,
        "entities": [],
        "documents": documents,
        "evidence": evidence,
        "relations": [],
        "activities": [],
        "contexts": [],
    }
    stable = content | {
        "documents": [
            {
                key: value
                for key, value in document.items()
                if key not in {"observationId", "observedAt"}
            }
            for document in documents
        ]
    }
    batch = {"id": "batch_" + digest(stable), **content}
    validate_batch(batch)
    return batch
