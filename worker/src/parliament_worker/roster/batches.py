"""Prepare review-only bounded wiki snapshots from source-local roster candidates."""

import hashlib
import json
import re
from typing import Any

from parliament_worker.http import validate_official_url
from parliament_worker.knowledge.review import validate_batch

OBSERVATIONS = frozenset(
    {
        "observationId",
        "collectedAt",
        "observedAt",
        "reviewedAt",
        "rawStorageKey",
        "corrected",
        "changedAt",
    }
)


def _snapshot_content(value: Any) -> Any:
    """Match the backend's observation-independent immutable snapshot contract."""
    if isinstance(value, dict):
        return {
            key: _snapshot_content(item)
            for key, item in value.items()
            if key not in OBSERVATIONS
        }
    if isinstance(value, list):
        return [_snapshot_content(item) for item in value]
    return value


def identity(namespace: str, value: str, prefix: str = "p") -> str:
    """Keep namespaces and exact external IDs distinct across source families."""
    return prefix + "_" + hashlib.sha256((namespace + ":" + value).encode()).hexdigest()


def _excerpt(record: dict[str, Any]) -> str:
    """Preserve explicit professional source fields, excluding contact information."""
    if record.get("excerpt"):
        return record["excerpt"]
    fields = [
        "name",
        "position",
        "organizationName",
        "party",
        "districtLabel",
        "termLabel",
        "committeeLabel",
        "currentness",
    ]
    return json.dumps(
        {key: record[key] for key in fields if record.get(key)},
        ensure_ascii=False,
        sort_keys=True,
    )


def candidate_batches(
    records: list[dict[str, Any]],
    identity_map: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Build source-evidenced private candidates without identity/publication approval.

    Args:
        records: Collected source-local records with fixed raw hashes and locators.
        identity_map: Explicit verified namespace:value to existing public ID map.

    Returns:
        Importable batches, at most 50 people plus 50 organizations each. Review
        decisions and unknown source usage terms remain unchanged.
    """
    mapping = identity_map or {}
    seen = set()
    batches = []
    for offset in range(0, len(records), 50):
        entities, documents, evidence = {}, [], []
        for record in records[offset : offset + 50]:
            namespace = record["namespace"]
            source_id = record["sourceRecordId"]
            key = namespace + ":" + source_id
            if key in seen:
                raise ValueError("duplicate roster source identity")
            seen.add(key)
            person_id = mapping.get(key, identity(namespace, source_id))
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", person_id):
                raise ValueError("invalid mapped public identity")
            validate_official_url(record["sourceUrl"])
            raw_hash = record["rawHash"]
            if not re.fullmatch(r"[a-f0-9]{64}", raw_hash):
                raise ValueError("invalid roster raw hash")
            org_namespace = record.get("organizationNamespace", namespace + "_ORG")
            org_code = record.get("organizationCode")
            if not isinstance(org_code, str) or not org_code:
                raise ValueError("roster organization identity required")
            org_id = identity(org_namespace, org_code, "org")
            document_id = identity(namespace, source_id, "roster_doc_v2")
            text = _excerpt(record)
            surface = record.get("nameSurface", record["name"])
            if not text.strip() or surface not in text:
                raise ValueError("source excerpt must contain exact candidate name")
            raw_format = record.get(
                "format", "json" if namespace == "OPEN_ASSEMBLY_MONA_CD" else "html"
            )
            start = text.index(surface)
            segment_content = {
                "text": text,
                "locator": record["evidenceLocator"],
                "surface": surface,
                "start": start,
                "end": start + len(surface),
                "candidatePersonId": person_id,
                "title": record["name"] + " · " + record["position"] + " 명부 근거",
                "bodyStatus": "available",
                "licenseStatus": record.get("licenseStatus", "unknown"),
                "publishedAt": record.get("sourcePublishedAt"),
                "datePrecision": record.get("datePrecision", "unknown"),
                "qualificationObservedAt": record.get("qualificationObservedAt"),
            }
            extraction = (
                "roster_v3_"
                + raw_format
                + "_"
                + hashlib.sha256(
                    json.dumps(
                        segment_content, ensure_ascii=False, sort_keys=True
                    ).encode()
                ).hexdigest()
            )
            evidence_id = identity(document_id + ":" + raw_hash, extraction, "ev")
            segment_id = "record"
            stamp = record["observedAt"]
            evidence.append(
                {
                    "id": evidence_id,
                    "documentId": document_id,
                    "documentVersion": raw_hash,
                    "extractionVersion": extraction,
                    "segmentId": segment_id,
                    "start": 0,
                    "end": len(text),
                }
            )
            documents.append(
                {
                    "id": document_id,
                    "version": raw_hash,
                    "sourceKey": "roster_" + namespace,
                    "recordKey": source_id,
                    "sourceUrl": record["sourceUrl"],
                    "title": record["name"] + " · " + record["position"] + " 명부 근거",
                    "format": raw_format,
                    "bodyStatus": "available",
                    "licenseStatus": record.get("licenseStatus", "unknown"),
                    "publishedAt": record.get("sourcePublishedAt"),
                    "collectedAt": record.get("firstCollectedAt", stamp),
                    "observedAt": stamp,
                    "rawStorageKey": "raw/" + raw_hash + ".bin",
                    "extractionVersion": extraction,
                    "datePrecision": record.get("datePrecision", "unknown"),
                    "observationId": identity(
                        document_id + ":" + raw_hash, stamp, "obs"
                    ),
                    "segments": [
                        {
                            "id": segment_id,
                            "text": text,
                            "locator": record["evidenceLocator"],
                            "mentions": [
                                {
                                    "id": identity(evidence_id, person_id, "mention"),
                                    "surface": surface,
                                    "start": start,
                                    "end": start + len(surface),
                                    "candidatePersonIds": [person_id],
                                    "personId": None,
                                    "decision": "pending",
                                }
                            ],
                        }
                    ],
                }
            )
            facts = [
                {
                    "label": "명부 현재성",
                    "value": record.get("currentness", "unknown"),
                    "evidenceIds": [evidence_id],
                }
            ]
            for field, label in [
                ("districtLabel", "선거구 원문 표기"),
                ("termLabel", "대수 원문 표기"),
                ("committeeLabel", "위원회 원문 표기"),
                ("identityStatus", "신원 연결 상태"),
            ]:
                if record.get(field):
                    facts.append(
                        {
                            "label": label,
                            "value": record[field],
                            "evidenceIds": [evidence_id],
                        }
                    )
            person = {
                "id": person_id,
                "kind": "person",
                "name": record["name"],
                "identifiers": [{"namespace": namespace, "value": source_id}],
                "facts": facts,
                "tenures": [
                    {
                        "organizationId": org_id,
                        "position": record["position"],
                        "party": record.get("party"),
                        "validFrom": record.get("validFrom"),
                        "validUntil": record.get("validUntil"),
                        "observedAt": record.get("qualificationObservedAt", stamp),
                        "evidenceIds": [evidence_id],
                    }
                ],
            }
            previous = entities.get(person_id)
            if previous:
                if previous["kind"] != "person":
                    raise ValueError("mapped identity kind collision")
                for field in ("identifiers", "facts", "tenures"):
                    previous[field].extend(person[field])
            else:
                entities[person_id] = person
            if org_id in entities and entities[org_id]["kind"] != "organization":
                raise ValueError("mapped identity kind collision")
            if org_id not in entities:
                entities[org_id] = {
                    "id": org_id,
                    "kind": "organization",
                    "name": record["organizationName"],
                    "identifiers": [{"namespace": org_namespace, "value": org_code}],
                    "facts": [],
                    "tenures": [],
                }
        batch = {
            "issueId": "current-politicians",
            "entities": list(entities.values()),
            "documents": documents,
            "evidence": evidence,
            "relations": [],
            "activities": [],
            "contexts": [],
        }
        encoded = json.dumps(
            _snapshot_content(batch),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        batch = {"id": "roster_batch_" + hashlib.sha256(encoded).hexdigest(), **batch}
        validate_batch(batch)
        batches.append(batch)
    return batches
