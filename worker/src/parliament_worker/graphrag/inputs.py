"""Adapt fixed knowledge evidence into bounded private GraphRAG text units."""

import hashlib
import json
from pathlib import Path
from typing import Any

from parliament_worker.graphrag.activity_sources import project_activity_roles
from parliament_worker.graphrag.source_forms import source_form
from parliament_worker.graphrag.source_safety import (
    contact_free_prefix,
    contains_contact,
)
from parliament_worker.http import validate_official_url
from parliament_worker.knowledge.files import private_read
from parliament_worker.knowledge.identifiers import validate_identifiers
from parliament_worker.knowledge.review import ID_PATTERN, validate_batch


def canonical(value: Any) -> bytes:
    """Serialize generation inputs independently of dictionary ordering."""
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def fingerprint(value: Any) -> str:
    """Hash exact semantic dependencies, excluding transient observations."""
    return hashlib.sha256(canonical(value)).hexdigest()


def split_interval(
    text: str, start: int, end: int, byte_limit: int = 850
) -> list[tuple[int, int]]:
    """Split every code point exactly once while bounding UTF-8 prompt bytes."""
    if not 0 <= start <= end <= len(text) or byte_limit < 4:
        raise ValueError("invalid source interval")
    intervals, left, used = [], start, 0
    for position in range(start, end):
        size = len(text[position].encode())
        if used + size > byte_limit:
            intervals.append((left, position))
            left, used = position, 0
        used += size
    if left < end:
        intervals.append((left, end))
    return intervals


def _identity(entity: dict[str, Any]) -> dict[str, Any]:
    validate_identifiers(entity.get("identifiers", []))
    if not ID_PATTERN.fullmatch(entity.get("id", "")) or entity.get("kind") not in {
        "person",
        "organization",
        "bill",
        "policy",
    }:
        raise ValueError("invalid graph identity")
    name = entity.get("name")
    if not isinstance(name, str) or not 1 <= len(name) <= 300:
        raise ValueError("invalid graph name")
    return {key: entity.get(key, []) for key in ("id", "kind", "name", "identifiers")}


def _person_in_safe_prefix(
    segment: dict[str, Any], person_id: str, name: str, start: int, end: int
) -> bool:
    """Verify the source's own name surface inside a contact-free interval.

    Args:
        segment: Fixed source segment with optional person mentions.
        person_id: Source-bound candidate ID from the tenure evidence.
        name: Canonical name used only when the segment has no mentions.
        start: Inclusive safe interval start in Unicode code points.
        end: Exclusive safe interval end in Unicode code points.

    Returns:
        Whether the exact interval names this particular source candidate.
    """
    mentions = segment.get("mentions", [])
    if not mentions:
        return name in segment["text"][start:end]
    return any(
        (
            person_id in mention.get("candidatePersonIds", [])
            or mention.get("personId") == person_id
        )
        and isinstance(mention.get("start"), int)
        and isinstance(mention.get("end"), int)
        and start <= mention["start"] < mention["end"] <= end
        and segment["text"][mention["start"] : mention["end"]] == mention.get("surface")
        for mention in mentions
    )


def sources_from_batch(batch: dict[str, Any]) -> list[dict[str, Any]]:
    """Retain source-local identities and fixed evidence, never copy raw files.

    Unknown-use sources supply only already selected factual evidence intervals.
    Allowed-use sources may supply full extracted text. Restricted sources retain
    metadata and an explicit missing-body state. All resulting sources are private;
    machine provenance checks do not replace identity or publication review.
    """
    try:
        validate_batch(batch)
    except (ValueError, TypeError, AttributeError, KeyError):
        raise ValueError("invalid GraphRAG knowledge batch") from None
    entities = {entity["id"]: _identity(entity) for entity in batch.get("entities", [])}
    tenure_proofs: dict[str, list[tuple[str, str]]] = {}
    for entity in batch.get("entities", []):
        if entity["kind"] != "person":
            continue
        for tenure in entity.get("tenures", []):
            organization = entities.get(tenure.get("organizationId"))
            if organization is None or organization["kind"] != "organization":
                continue
            for evidence_id in tenure.get("evidenceIds", []):
                tenure_proofs.setdefault(evidence_id, []).append(
                    (entity["id"], entity["name"], organization["name"])
                )
    issue_policy_id = batch.get("issuePolicyId")
    issue_policy = entities.get(issue_policy_id) if issue_policy_id else None
    evidence = batch.get("evidence", [])
    ownership: dict[str, set[str]] = {}
    for entity in batch.get("entities", []):
        for fact in entity.get("facts", []) + entity.get("tenures", []):
            for identifier in fact.get("evidenceIds", []):
                ownership.setdefault(identifier, set()).add(entity["id"])
            if fact.get("organizationId"):
                for identifier in fact.get("evidenceIds", []):
                    ownership.setdefault(identifier, set()).add(fact["organizationId"])
    for relation in batch.get("relations", []):
        for identifier in relation.get("evidenceIds", []):
            ownership.setdefault(identifier, set()).update(
                [relation.get("subjectId"), relation.get("objectId")]
            )
    result = []
    for document in batch.get("documents", []):
        validate_official_url(document["sourceUrl"])
        for key in ("id", "version", "extractionVersion"):
            if not ID_PATTERN.fullmatch(document.get(key, "")):
                raise ValueError("invalid fixed document identity")
        scope = document["sourceKey"] + ":" + document["recordKey"]
        if not 1 <= len(scope) <= 600:
            raise ValueError("invalid source scope")
        fixed = {
            key: document.get(key)
            for key in (
                "id",
                "version",
                "extractionVersion",
                "sourceUrl",
                "sourceKey",
                "recordKey",
                "title",
                "licenseStatus",
                "bodyStatus",
                "publishedAt",
                "datePrecision",
            )
        }
        selected = [
            item
            for item in evidence
            if (
                item.get("documentId"),
                item.get("documentVersion"),
                item.get("extractionVersion"),
            )
            == (document["id"], document["version"], document["extractionVersion"])
        ]
        segment_map = {s["id"]: s for s in document.get("segments", [])}
        entity_ids = set()
        ranges: dict[str, list[tuple[int, int]]] = {}
        for item in selected:
            segment = segment_map.get(item.get("segmentId"))
            if (
                segment is None
                or type(item.get("start")) is not int
                or type(item.get("end")) is not int
            ):
                raise ValueError("missing fixed graph evidence")
            if not 0 <= item["start"] < item["end"] <= len(segment["text"]):
                raise ValueError("invalid fixed graph evidence interval")
            ranges.setdefault(segment["id"], []).append((item["start"], item["end"]))
            entity_ids.update(ownership.get(item["id"], set()))
        for segment in segment_map.values():
            for mention in segment.get("mentions", []):
                entity_ids.update(mention.get("candidatePersonIds", []))
                if mention.get("personId"):
                    entity_ids.add(mention["personId"])
        units = []
        omitted_contact = False
        usable = (
            document.get("bodyStatus")
            in {
                "available",
                "partial",
            }
            and document.get("licenseStatus") != "restricted"
        )
        for segment in segment_map.values():
            if not usable:
                continue
            intervals = (
                [(0, len(segment["text"]))]
                if document.get("licenseStatus") == "allowed"
                else ranges.get(segment["id"], [])
            )
            merged: list[tuple[int, int]] = []
            for start, end in sorted(set(intervals)):
                if merged and start <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
                else:
                    merged.append((start, end))
            for start, end in merged:
                selected_text = segment["text"][start:end]
                if contains_contact(selected_text):
                    omitted_contact = True
                    if document.get("licenseStatus") != "unknown":
                        continue
                    prefix = contact_free_prefix(selected_text)
                    if not prefix or not any(
                        item["segmentId"] == segment["id"]
                        and item["start"] <= start
                        and start + len(prefix) <= item["end"]
                        and organization_name in prefix
                        and _person_in_safe_prefix(
                            segment, person_id, person_name, start, start + len(prefix)
                        )
                        for item in selected
                        for person_id, person_name, organization_name in tenure_proofs.get(
                            item["id"], []
                        )
                    ):
                        continue
                    end = start + len(prefix)
                for left, right in split_interval(segment["text"], start, end):
                    coordinates = {
                        "documentId": document["id"],
                        "documentVersion": document["version"],
                        "extractionVersion": document["extractionVersion"],
                        "segmentId": segment["id"],
                        "start": left,
                        "end": right,
                    }
                    units.append(
                        {
                            "id": "tu_" + fingerprint(coordinates),
                            **coordinates,
                            "text": segment["text"][left:right],
                            "locator": segment.get("locator"),
                            "sourceUrl": document["sourceUrl"],
                            "licenseStatus": document.get("licenseStatus"),
                        }
                    )
        if issue_policy and any(
            source_form(unit["text"], issue_policy["name"]) for unit in units
        ):
            entity_ids.add(issue_policy_id)
        document_bill_ids = [
            entity["id"]
            for entity in entities.values()
            if entity["kind"] == "bill"
            and document["sourceKey"] == "lawmaking-bill-detail"
            and any(
                identifier
                == {
                    "namespace": "ASSEMBLY_BILL_NUMBER",
                    "value": document["recordKey"],
                }
                for identifier in entity["identifiers"]
            )
        ]
        if len(document_bill_ids) > 1:
            raise ValueError("ambiguous bill record identity")
        document_bill_id = document_bill_ids[0] if document_bill_ids else None
        if document_bill_id:
            entity_ids.add(document_bill_id)
        payload = {
            "document": fixed,
            "units": units,
            "entities": [entities[e] for e in sorted(entity_ids) if e in entities],
            "public": False,
            "issueId": batch.get("issueId"),
            **(
                {"issuePolicyId": issue_policy_id}
                if issue_policy_id in entity_ids
                else {}
            ),
            **({"documentBillId": document_bill_id} if document_bill_id else {}),
            "bodyCoverage": (
                "full"
                if document.get("licenseStatus") == "allowed"
                and document.get("bodyStatus") == "available"
                and not omitted_contact
                else (
                    "partial"
                    if document.get("licenseStatus") == "allowed" and units
                    else "selected_evidence" if units else "unavailable"
                )
            ),
        }
        selected_ids = {item["id"] for item in selected}
        lineage = [
            {
                "type": relation["type"],
                "subjectId": relation["subjectId"],
                "objectId": relation["objectId"],
            }
            for relation in batch.get("relations", [])
            if relation["type"] == "incorporated_into_alternative"
            and selected_ids.intersection(relation.get("evidenceIds", []))
            and relation["subjectId"] in entity_ids
            and relation["objectId"] in entity_ids
        ]
        if lineage:
            payload["relationCandidates"] = sorted(
                lineage, key=lambda item: (item["subjectId"], item["objectId"])
            )
        payload.update(
            project_activity_roles(batch, document, selected, units, entities)
        )
        result.append(
            {
                "scope": scope,
                "fingerprint": fingerprint(payload),
                "payload": payload,
                "observedAt": document.get("observedAt")
                or document.get("collectedAt")
                or "",
            }
        )
    return result


def read_sources(paths: list[Path]) -> list[dict[str, Any]]:
    """Read explicit complete input sets; a failed scan never signals deletion."""
    from parliament_worker.graphrag.source_observations import normalize_observed_at

    selected: dict[str, dict[str, Any]] = {}
    for path in paths:
        if path.is_symlink() or not path.exists():
            raise ValueError("input boundary is missing or unsafe")
        files = sorted(path.glob("*.json")) if path.is_dir() else [path]
        if not files:
            raise ValueError("empty input boundary requires explicit retirement")
        for file in files:
            batch = json.loads(private_read(file, max_bytes=10_000_000))
            if (
                not isinstance(batch, dict)
                or "documents" not in batch
                or "entities" not in batch
            ):
                raise ValueError("graph input must be a knowledge batch")
            for source in sources_from_batch(batch):
                source["observedAt"] = normalize_observed_at(source["observedAt"]) or ""
                previous = selected.get(source["scope"])
                if previous is None or source["observedAt"] > previous["observedAt"]:
                    selected[source["scope"]] = source
                elif (
                    source["observedAt"] == previous["observedAt"]
                    and source["fingerprint"] != previous["fingerprint"]
                ):
                    raise ValueError("conflicting source observations require review")
    return [selected[key] for key in sorted(selected)]
