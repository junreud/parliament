"""Compare inferred office edges with independently typed roster tenures."""

from collections import defaultdict
from pathlib import Path
from typing import Any

from parliament_worker.graphrag.index import current_artifacts
from parliament_worker.graphrag.source_forms import source_form
from parliament_worker.graphrag.source_safety import contains_contact
from parliament_worker.graphrag.store import GraphStore
from parliament_worker.knowledge.review import read_batch


def _batch_paths(inputs: list[Path]) -> list[Path]:
    """Expand explicit private batch boundaries without following symlinks."""
    files = []
    for path in inputs:
        if path.is_symlink() or not path.exists():
            raise ValueError("office audit input boundary is missing or unsafe")
        selected = sorted(path.glob("*.json")) if path.is_dir() else [path]
        if not selected or any(
            item.is_symlink() or not item.is_file() for item in selected
        ):
            raise ValueError("office audit input batch is missing or unsafe")
        files.extend(selected)
    if not files:
        raise ValueError("office audit requires an input batch")
    return files


def typed_office_pairs(inputs: list[Path]) -> set[tuple[str, str]]:
    """Read verified person-to-organization tenure IDs from input batches."""
    return {
        (entity["id"], tenure["organizationId"])
        for path in _batch_paths(inputs)
        for entity in read_batch(path)["entities"]
        if entity["kind"] == "person"
        for tenure in entity.get("tenures", [])
    }


def _review_proof(
    proof: dict[str, Any], source: dict[str, Any] | None
) -> dict[str, Any]:
    """Show a quote only when it matches the current fixed source interval."""
    units = source["payload"]["units"] if source else []
    unit = next((item for item in units if item["id"] == proof.get("unitId")), None)
    fixed = (
        "documentId",
        "documentVersion",
        "extractionVersion",
        "segmentId",
        "sourceUrl",
    )
    source_unit_ids = proof.get("sourceUnitIds")
    if unit is None and isinstance(source_unit_ids, list) and len(source_unit_ids) >= 2:
        indices = {item["id"]: index for index, item in enumerate(units)}
        if (
            all(isinstance(identifier, str) for identifier in source_unit_ids)
            and len(set(source_unit_ids)) == len(source_unit_ids)
            and all(identifier in indices for identifier in source_unit_ids)
        ):
            positions = [indices[identifier] for identifier in source_unit_ids]
            if positions == list(range(positions[0], positions[0] + len(positions))):
                group = [units[position] for position in positions]
                first = group[0]
                if all(
                    all(item.get(field) == first.get(field) for field in fixed)
                    and previous["end"] == item["start"]
                    and item["end"] - item["start"] == len(item["text"])
                    for previous, item in zip(group, group[1:])
                ):
                    unit = {
                        **first,
                        "start": first["start"],
                        "end": group[-1]["end"],
                        "text": "".join(item["text"] for item in group),
                    }
    start, end = proof.get("start"), proof.get("end")
    exact = bool(
        unit
        and all(proof.get(field) == unit.get(field) for field in fixed)
        and type(start) is int
        and type(end) is int
        and unit["start"] <= start < end <= unit["end"]
        and proof.get("text")
        == unit["text"][start - unit["start"] : end - unit["start"]]
    )
    contact_omitted = exact and contains_contact(proof["text"])
    return {
        "documentId": proof.get("documentId"),
        "documentVersion": proof.get("documentVersion"),
        "extractionVersion": proof.get("extractionVersion"),
        "segmentId": proof.get("segmentId"),
        "unitId": proof.get("unitId"),
        "sourceUnitIds": source_unit_ids,
        "start": start,
        "end": end,
        "sourceUrl": unit["sourceUrl"] if exact else None,
        "locator": unit.get("locator") if exact else None,
        "quote": proof["text"] if exact and not contact_omitted else None,
        "exactMatch": exact,
        "contactOmitted": contact_omitted,
    }


def audit_office_edges(store: GraphStore, inputs: list[Path]) -> dict[str, Any]:
    """Flag inferred office links absent from structured, evidence-bound tenures.

    Args:
        store: Private GraphRAG state containing current candidate projections.
        inputs: Explicit validated KnowledgeBatch files or directories.

    Returns:
        Private review report. A match is corroboration, never publication approval.
    """
    tenures: dict[str, set[str]] = {}
    people: dict[str, str] = {}
    organizations: dict[str, str] = {}
    files = _batch_paths(inputs)
    for path in files:
        batch = read_batch(path)
        for entity in batch["entities"]:
            if entity["kind"] == "person":
                people[entity["id"]] = entity["name"]
                tenures.setdefault(entity["id"], set()).update(
                    item["organizationId"] for item in entity.get("tenures", [])
                )
            elif entity["kind"] == "organization":
                organizations[entity["id"]] = entity["name"]

    sources = store.sources()
    sources_by_scope = {source["scope"]: source for source in sources}
    matched, total = 0, 0
    items = []
    review_queue = []
    inferred_pairs: set[tuple[str, str]] = set()
    alternate_by_name: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    graphs = current_artifacts(store, "graph")
    for graph in graphs:
        dependencies = graph["dependency"].get("sources", [])
        scope = dependencies[0]["scope"] if len(dependencies) == 1 else None
        source = sources_by_scope.get(scope) if scope else None
        nodes = {node["id"]: node for node in graph["payload"]["nodes"]}
        for edge in graph["payload"]["edges"]:
            if edge["type"] != "holds_office":
                continue
            total += 1
            evidence = edge.get("evidence") or []
            known = tenures.get(edge["source"], set())
            review_queue.append(
                {
                    "edgeId": edge["id"],
                    "personId": edge["source"],
                    "personName": nodes[edge["source"]]["name"],
                    "organizationId": edge["target"],
                    "organizationName": nodes[edge["target"]]["name"],
                    "typedTenureMatched": edge["target"] in known,
                    "sourceScope": scope,
                    "licenseStatus": (
                        source["payload"]["document"].get("licenseStatus")
                        if source
                        else "unknown"
                    ),
                    "evidence": [_review_proof(proof, source) for proof in evidence],
                    "decision": "pending",
                }
            )
            inferred_pairs.add((edge["source"], edge["target"]))
            alternate_by_name[
                (nodes[edge["source"]]["name"], nodes[edge["target"]]["name"])
            ].append(
                {
                    "edgeId": edge["id"],
                    "personId": edge["source"],
                    "organizationId": edge["target"],
                }
            )
            if edge["target"] in known:
                matched += 1
                continue
            evidence = edge.get("evidence") or [{}]
            items.append(
                {
                    "edgeId": edge["id"],
                    "personId": edge["source"],
                    "personName": nodes[edge["source"]]["name"],
                    "inferredOrganizationId": edge["target"],
                    "inferredOrganizationName": nodes[edge["target"]]["name"],
                    "typedOrganizationIds": sorted(known),
                    "typedOrganizationNames": [
                        organizations.get(identifier) for identifier in sorted(known)
                    ],
                    "sourceDocumentId": evidence[0].get("documentId"),
                    "evidenceUnitId": evidence[0].get("unitId"),
                    "decision": "pending",
                    "reason": "not_matched_to_typed_tenure",
                }
            )
    sources_by_person: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source in sources:
        for entity in source["payload"]["entities"]:
            if entity["kind"] == "person":
                sources_by_person[entity["id"]].append(source)
    pending_pairs: set[tuple[str, str]] = set()
    for job in store.jobs():
        if job["state"] not in {
            "planned",
            "deferred",
            "submitting",
            "polling",
        } or not job["context"].get("repair_version"):
            continue
        aliases = list(job["context"].get("aliases", {}).values())
        pending_pairs.update(
            (person["id"], organization["id"])
            for person in aliases
            if person["kind"] == "person"
            for organization in aliases
            if organization["kind"] == "organization"
        )
    missing_items = []
    for person_id, organization_ids in sorted(tenures.items()):
        for organization_id in sorted(organization_ids):
            if (person_id, organization_id) in inferred_pairs:
                continue
            person_name = people[person_id]
            organization_name = organizations.get(organization_id)
            source_evidence = []
            for source in sources_by_person[person_id]:
                payload = source["payload"]
                if organization_id not in {
                    entity["id"] for entity in payload["entities"]
                }:
                    continue
                document = payload["document"]
                exact_co_mention = bool(
                    organization_name
                    and any(
                        source_form(unit["text"], person_name)
                        and source_form(unit["text"], organization_name)
                        for unit in payload["units"]
                    )
                )
                source_evidence.append(
                    {
                        "scope": source["scope"],
                        "sourceUrl": document["sourceUrl"],
                        "licenseStatus": document["licenseStatus"],
                        "unitCount": len(payload["units"]),
                        "exactCoMention": exact_co_mention,
                    }
                )
            alternate = [
                candidate
                for candidate in alternate_by_name.get(
                    (person_name, organization_name), []
                )
                if (
                    candidate["personId"],
                    candidate["organizationId"],
                )
                != (person_id, organization_id)
            ]
            if (person_id, organization_id) in pending_pairs:
                gap_reason = "model_pending"
            elif alternate:
                gap_reason = "identity_review"
            elif source_evidence and all(
                item["licenseStatus"] == "restricted" for item in source_evidence
            ):
                gap_reason = "source_use_restricted"
            elif any(item["exactCoMention"] for item in source_evidence):
                gap_reason = "same_span_not_inferred"
            elif any(item["unitCount"] for item in source_evidence):
                gap_reason = "source_span_gap"
            elif source_evidence:
                gap_reason = "source_body_missing"
            else:
                gap_reason = "no_shared_source"
            missing_items.append(
                {
                    "personId": person_id,
                    "personName": person_name,
                    "organizationId": organization_id,
                    "organizationName": organization_name,
                    "decision": "pending",
                    "reason": "typed_tenure_without_inferred_edge",
                    "gapReason": gap_reason,
                    "sourceEvidence": sorted(
                        source_evidence, key=lambda item: item["scope"]
                    ),
                    "alternateIdentityCandidates": sorted(
                        alternate, key=lambda item: item["edgeId"]
                    ),
                }
            )
    return {
        "schema": "parliament-graphrag-office-audit-v1",
        "public": False,
        "inputFiles": len(files),
        "currentGraphUnits": len(graphs),
        "totalOfficeEdges": total,
        "matchedTypedTenure": matched,
        "reviewRequired": len(items),
        "items": sorted(items, key=lambda item: item["edgeId"]),
        "reviewQueueCount": len(review_queue),
        "reviewQueue": sorted(review_queue, key=lambda item: item["edgeId"]),
        "missingTypedTenures": len(missing_items),
        "missingItems": missing_items,
    }
