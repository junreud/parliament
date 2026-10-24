"""Translate current, exact graph policy links into a private review batch."""

from copy import deepcopy
from typing import Any

from parliament_worker.graphrag.index import select_snapshot_artifacts
from parliament_worker.graphrag.inputs import sources_from_batch
from parliament_worker.graphrag.source_forms import source_form
from parliament_worker.knowledge.extract import digest
from parliament_worker.knowledge.review import validate_batch


def _proof(
    proof: dict[str, Any],
    document: dict[str, Any],
    units: list[dict[str, Any]],
) -> dict[str, Any]:
    """Require a graph quote to be an exact interval of a fixed batch segment."""
    segment = next(
        (item for item in document["segments"] if item["id"] == proof.get("segmentId")),
        None,
    )
    start, end = proof.get("start"), proof.get("end")
    if (
        segment is None
        or type(start) is not int
        or type(end) is not int
        or not 0 <= start < end <= len(segment["text"])
        or proof.get("documentId") != document["id"]
        or proof.get("documentVersion") != document["version"]
        or proof.get("extractionVersion") != document["extractionVersion"]
        or proof.get("sourceUrl") != document["sourceUrl"]
        or proof.get("text") != segment["text"][start:end]
        or not any(
            all(
                unit.get(field) == proof.get(field)
                for field in (
                    "documentId",
                    "documentVersion",
                    "extractionVersion",
                    "segmentId",
                    "sourceUrl",
                )
            )
            and unit["start"] <= start < end <= unit["end"]
            and (proof.get("unitId") is None or proof["unitId"] == unit["id"])
            for unit in units
        )
    ):
        raise ValueError("graph proof does not match pinned source segment")
    evidence_id = "evidence_gr_" + digest(
        [
            document["id"],
            document["version"],
            document["extractionVersion"],
            segment["id"],
            start,
            end,
        ]
    )
    return {
        "id": evidence_id,
        "documentId": document["id"],
        "documentVersion": document["version"],
        "extractionVersion": document["extractionVersion"],
        "segmentId": segment["id"],
        "start": start,
        "end": end,
    }


def merge_review_batch(
    batch: dict[str, Any], snapshot: dict[str, Any]
) -> dict[str, Any]:
    """Create an immutable pending packet for current bill-to-policy candidates.

    Args:
        batch: Operator-selected, validated source KnowledgeBatch.
        snapshot: One consistent private GraphRAG source/artifact snapshot.

    Returns:
        A new private KnowledgeBatch-shaped packet. It cannot publish itself.

    Raises:
        ValueError: A selected graph proof contradicts its pinned batch source.
    """
    validate_batch(batch)
    output = deepcopy(batch)
    output.pop("issuePolicyId", None)  # Graph input hint is not a Java batch field.
    expected_sources = {item["scope"]: item for item in sources_from_batch(batch)}
    current_sources = {item["scope"]: item for item in snapshot["sources"]}
    documents = {
        item["sourceKey"] + ":" + item["recordKey"]: item for item in batch["documents"]
    }
    entities = {item["id"]: item for item in batch["entities"]}
    existing_pairs = {
        (item["subjectId"], item["type"], item["objectId"])
        for item in batch["relations"]
    }
    pending: dict[tuple[str, str, str], dict[str, dict[str, Any]]] = {}
    for graph in select_snapshot_artifacts(snapshot, "graph"):
        dependencies = graph["dependency"].get("sources", [])
        if len(dependencies) != 1:
            continue
        dependency = dependencies[0]
        scope = dependency["scope"]
        source = current_sources.get(scope)
        expected = expected_sources.get(scope)
        document = documents.get(scope)
        if (
            source is None
            or expected is None
            or document is None
            or source["fingerprint"] != expected["fingerprint"]
        ):
            continue
        payload = source["payload"]
        if (
            payload["document"]["id"] != document["id"]
            or payload["document"]["version"] != document["version"]
            or payload["document"]["extractionVersion"] != document["extractionVersion"]
        ):
            continue
        local_entities = {item["id"] for item in payload["entities"]}
        for edge in graph["payload"].get("edges", []):
            if edge.get("type") != "concerns" or edge.get("decision") == "rejected":
                continue
            subject, target = edge["source"], edge["target"]
            pair = (subject, "concerns", target)
            if pair in existing_pairs:
                continue
            if (
                subject not in local_entities
                or target not in local_entities
                or entities.get(subject, {}).get("kind") != "bill"
                or entities.get(target, {}).get("kind") != "policy"
                or payload.get("documentBillId") != subject
                or payload.get("issuePolicyId") != target
                or document["sourceKey"] != "lawmaking-bill-detail"
                or not edge.get("documentIdentitySupported")
            ):
                raise ValueError("graph policy identity does not match source")
            if not edge.get("evidence"):
                raise ValueError("graph policy relation lacks evidence")
            citations = pending.setdefault(pair, {})
            for item in edge["evidence"]:
                evidence = _proof(item, document, payload["units"])
                if not source_form(item["text"], entities[target]["name"]):
                    raise ValueError("graph proof does not name policy")
                citations[evidence["id"]] = evidence
    known_evidence = {item["id"]: item for item in output["evidence"]}
    for pair, citations in sorted(pending.items()):
        for identifier, item in sorted(citations.items()):
            previous = known_evidence.get(identifier)
            if previous is not None and previous != item:
                raise ValueError("graph evidence identity conflict")
            if previous is None:
                output["evidence"].append(item)
                known_evidence[identifier] = item
        relation_id = "relation_gr_" + digest([*pair, sorted(citations)])
        if any(item["id"] == relation_id for item in output["relations"]):
            raise ValueError("graph relation identity conflict")
        output["relations"].append(
            {
                "id": relation_id,
                "subjectId": pair[0],
                "type": pair[1],
                "objectId": pair[2],
                "evidenceIds": sorted(citations),
                "decision": "pending",
                "reason": "GraphRAG 원문 연결 후보. 사실·출처 이용·공개 여부 검수 필요.",
            }
        )
    output["id"] = "graph-review-" + digest(
        [batch["id"], output["relations"], output["evidence"]]
    )
    validate_batch(output)
    return output
