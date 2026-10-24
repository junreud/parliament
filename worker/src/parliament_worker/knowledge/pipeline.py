"""Selected historical documents bypass the rolling announcement window."""

import json
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from parliament_worker.http import validate_official_url
from parliament_worker.knowledge.extract import (
    EXTRACTOR_VERSION,
    digest,
    extract_document,
)
from parliament_worker.knowledge.identifiers import validate_identifiers
from parliament_worker.knowledge.store import PilotStore

ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,128}")


def validate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Validate an operator-selected bounded source manifest before fetching."""
    for name in ("id", "issueId"):
        if not isinstance(manifest.get(name), str) or not ID_PATTERN.fullmatch(
            manifest[name]
        ):
            raise ValueError("invalid manifest identity")
    documents = manifest.get("documents")
    entities = manifest.get("entities")
    if (
        not isinstance(documents, list)
        or not 1 <= len(documents) <= 50
        or not isinstance(entities, list)
        or len(entities) > 100
    ):
        raise ValueError("invalid manifest bounds")
    document_ids = set()
    source_ids = set()
    for spec in documents:
        if not ID_PATTERN.fullmatch(spec.get("id", "")) or spec["id"] in document_ids:
            raise ValueError("invalid document identity")
        document_ids.add(spec["id"])
        identity = (spec.get("sourceKey"), spec.get("recordKey"))
        if (
            any(
                not isinstance(value, str) or not 1 <= len(value) <= 255
                for value in identity
            )
            or identity in source_ids
        ):
            raise ValueError("invalid source identity")
        source_ids.add(identity)
        validate_official_url(spec["sourceUrl"])
        if spec.get("referer"):
            validate_official_url(spec["referer"])
        if spec.get("format") not in {"html", "json", "pdf", "hwp", "hwpx"}:
            raise ValueError("invalid source format")
        alt_selector = spec.get("imageAltSelector")
        if alt_selector is not None and (
            spec["format"] != "html"
            or not isinstance(alt_selector, str)
            or not 1 <= len(alt_selector) <= 200
        ):
            raise ValueError("invalid image alt selector")
    entity_ids = set()
    for entity in entities:
        validate_identifiers(entity.get("identifiers", []))
        if (
            not ID_PATTERN.fullmatch(entity.get("id", ""))
            or entity["id"] in entity_ids
            or entity.get("kind") not in {"person", "organization", "bill", "policy"}
            or not isinstance(entity.get("name"), str)
            or not entity["name"].strip()
        ):
            raise ValueError("invalid entity identity")
        entity_ids.add(entity["id"])
    issue_policy_id = manifest.get("issuePolicyId")
    if issue_policy_id is not None and not any(
        entity["id"] == issue_policy_id and entity["kind"] == "policy"
        for entity in entities
    ):
        raise ValueError("invalid issue policy identity")
    return manifest


def read_manifest(path: Path) -> dict[str, Any]:
    """Load a small explicit manifest; no directory discovery or recursive crawl."""
    if path.stat().st_size > 1_000_000:
        raise ValueError("manifest size exceeds limit")
    return validate_manifest(json.loads(path.read_text(encoding="utf-8")))


def collect_manifest(
    manifest: dict[str, Any],
    fetcher: Callable[..., bytes],
    store: PilotStore,
    job_id: str,
    collected_at: datetime,
    *,
    cloud_store: Any = None,
) -> dict[str, Any]:
    """Collect selected URLs sequentially and preserve successes and failures.

    Args:
        manifest: Operator-selected official source declarations.
        fetcher: URL and redirect validating bounded fetcher.
        store: Private immutable local store.
        job_id: Replay identity for one collection run.
        collected_at: Run observation time, independent of source dates.
        cloud_store: Explicitly enabled optional immutable S3 adapter.

    Returns:
        Safe collection counts and observations, without private raw content.
    """
    validate_manifest(manifest)
    if not ID_PATTERN.fullmatch(job_id):
        raise ValueError("invalid job identity")
    observations = []
    for spec in manifest["documents"]:
        prior = store.observations(spec["id"], job_id=job_id)
        if prior:
            if prior[0]["spec"] != spec:
                raise ValueError("job replay manifest conflict")
            if cloud_store and prior[0]["status"] == "success":
                cloud_store.save(
                    spec["sourceKey"], spec["recordKey"], store.read_raw(prior[0])
                )
            observations.extend(prior)
            continue
        try:
            raw = (
                fetcher(spec["sourceUrl"], referer=spec["referer"])
                if spec.get("referer")
                else fetcher(spec["sourceUrl"])
            )
            observed = store.observe(spec, raw, job_id, collected_at)
            observations.append(observed)
            if cloud_store:
                cloud_store.save(spec["sourceKey"], spec["recordKey"], raw)
        except Exception as error:
            if store.observations(spec["id"], job_id=job_id):
                raise
            store.failure(spec, job_id, collected_at, type(error).__name__)
            observations.extend(store.observations(spec["id"], job_id=job_id))
    return {
        "manifestId": manifest["id"],
        "jobId": job_id,
        "successes": sum(item["status"] == "success" for item in observations),
        "failures": sum(item["status"] == "failed" for item in observations),
        "observations": observations,
    }


def prepare_batch(
    manifest: dict[str, Any],
    store: PilotStore,
    job_id: str,
    *,
    extractor_version: str = EXTRACTOR_VERSION,
) -> dict[str, Any]:
    """Prepare pending name/evidence candidates; never infer roles or publication."""
    validate_manifest(manifest)
    documents, evidence = [], []
    for spec in manifest["documents"]:
        observations = store.observations(spec["id"], job_id=job_id)
        if not observations:
            raise ValueError("document has not been collected in this job")
        observation = observations[0]
        if any(
            observation["spec"].get(key) != spec.get(key)
            for key in ("id", "sourceKey", "recordKey", "sourceUrl", "format")
        ):
            raise ValueError("source identity changed since collection")
        if observation["status"] != "success":
            continue
        extracted = extract_document(
            store.read_raw(observation),
            spec,
            manifest["entities"],
            extractor_version=extractor_version,
        )
        store.save_extraction(spec["id"], extracted)
        status = extracted["bodyStatus"]
        wire_status = (
            "unsupported"
            if status.startswith("unsupported_")
            else (
                "failed"
                if status.startswith("extraction_")
                else (
                    "unavailable"
                    if status in {"metadata_only", "scan_requires_ocr"}
                    else status
                )
            )
        )
        documents.append(
            {
                "id": spec["id"],
                "version": observation["version"],
                "sourceKey": spec["sourceKey"],
                "recordKey": spec["recordKey"],
                "sourceUrl": spec["sourceUrl"],
                "title": extracted["title"] or spec.get("title", spec["recordKey"]),
                "format": spec["format"],
                "bodyStatus": wire_status,
                "licenseStatus": extracted["licenseStatus"],
                "publishedAt": extracted["publishedAt"],
                "datePrecision": (
                    "date"
                    if extracted["publishedPrecision"] == "day"
                    else extracted["publishedPrecision"]
                ),
                **store.version_metadata(observation),
                "rawStorageKey": observation["rawStorageKey"],
                "extractionVersion": extracted["extractionVersion"],
                "segments": extracted["segments"],
                "observationId": observation["observationId"],
                "observedAt": observation["observedAt"],
            }
        )
        for segment in extracted["segments"]:
            evidence.append(
                {
                    "id": "evidence_"
                    + digest([segment["id"], 0, len(segment["text"])]),
                    "documentId": spec["id"],
                    "documentVersion": observation["version"],
                    "extractionVersion": extracted["extractionVersion"],
                    "segmentId": segment["id"],
                    "start": 0,
                    "end": len(segment["text"]),
                }
            )
    entities = [
        {
            "id": entity["id"],
            "kind": entity["kind"],
            "name": entity["name"],
            "identifiers": entity.get("identifiers", []),
            "facts": [],
            "tenures": [],
        }
        for entity in manifest["entities"]
    ]
    content = {
        "issueId": manifest["issueId"],
        **(
            {"issuePolicyId": manifest["issuePolicyId"]}
            if "issuePolicyId" in manifest
            else {}
        ),
        "entities": entities,
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
    return {"id": "batch_" + digest(stable), **content}
