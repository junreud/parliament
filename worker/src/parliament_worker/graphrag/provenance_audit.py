"""Audit private graph and community proofs against pinned source revisions."""

import re
from collections import Counter
from typing import Any

from parliament_worker.graphrag.index import (
    select_snapshot_artifacts,
    source_dependency,
)
from parliament_worker.graphrag.office_repair import validate_composite_source_proof
from parliament_worker.graphrag.prompts import valid_relation_endpoints
from parliament_worker.graphrag.source_forms import source_form

PROOF_FIELDS = (
    "documentId",
    "documentVersion",
    "extractionVersion",
    "segmentId",
)


def _proof_within(parent: dict[str, Any], child: dict[str, Any]) -> bool:
    """Check that a cited quote is an exact substring of a child proof."""
    if any(parent.get(field) != child.get(field) for field in PROOF_FIELDS):
        return False
    start, end = child.get("start"), child.get("end")
    if type(start) is not int or type(end) is not int:
        return False
    if not parent["start"] <= start < end <= parent["end"]:
        return False
    return parent["text"][start - parent["start"] : end - parent["start"]] == child.get(
        "text"
    )


def _source_proof_valid(
    proof: dict[str, Any], units: dict[str, tuple[dict[str, Any], dict[str, Any]]]
) -> bool:
    """Reconstruct a normal or joined proof from current immutable source units."""
    source_unit_ids = proof.get("sourceUnitIds")
    if source_unit_ids is not None:
        if not isinstance(source_unit_ids, list) or not source_unit_ids:
            return False
        first = units.get(source_unit_ids[0])
        if first is None or any(
            units.get(unit_id, (None,))[0] is not first[0]
            for unit_id in source_unit_ids
        ):
            return False
        source, unit = first
        if proof.get("sourceUrl") != unit.get("sourceUrl"):
            return False
        try:
            validate_composite_source_proof(
                {
                    "sources": [source_dependency(source)],
                    "units": {"joined": proof},
                },
                source,
            )
        except (KeyError, TypeError, ValueError):
            return False
        return True
    pair = units.get(proof.get("unitId"))
    if pair is None:
        # Deterministic bill-lineage edges cite a fixed interval without an
        # inference unit ID. Reject a wrong explicit ID rather than falling back.
        if proof.get("unitId") is not None:
            return False
        return any(
            proof.get("sourceUrl") == unit.get("sourceUrl")
            and all(proof.get(field) == unit.get(field) for field in PROOF_FIELDS)
            and _proof_within(unit, proof)
            for _, unit in units.values()
        )
    _, unit = pair
    if any(
        proof.get(field) != unit.get(field) for field in (*PROOF_FIELDS, "sourceUrl")
    ):
        return False
    return _proof_within(unit, proof)


def _document_bill_identity_valid(
    graph: dict[str, Any],
    edge: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
    sources: dict[str, dict[str, Any]],
) -> bool:
    """Recheck a bill-to-policy claim against its exact official record number."""
    dependencies = graph["dependency"].get("sources", [])
    if len(dependencies) != 1:
        return False
    source = sources.get(dependencies[0]["scope"])
    if source is None or source_dependency(source) != dependencies[0]:
        return False
    payload = source["payload"]
    document = payload.get("document", {})
    bill, policy = nodes.get(edge["source"], {}), nodes.get(edge["target"], {})
    number = document.get("recordKey")
    return (
        edge["type"] == "concerns"
        and document.get("sourceKey") == "lawmaking-bill-detail"
        and payload.get("documentBillId") == edge["source"]
        and bill.get("kind") == "bill"
        and policy.get("kind") == "policy"
        and any(
            identifier == {"namespace": "ASSEMBLY_BILL_NUMBER", "value": number}
            for identifier in bill.get("identifiers", [])
        )
        and bool(edge.get("evidence"))
        and all(
            proof.get("documentId") == document.get("id")
            and source_form(proof.get("text", ""), policy.get("name", ""))
            for proof in edge["evidence"]
        )
    )


def _lineage_evidence_complete(
    edge: dict[str, Any], nodes: dict[str, dict[str, Any]]
) -> bool:
    """Require the original bill, alternative title, and decision across proofs."""
    original = nodes.get(edge.get("source"), {})
    alternative = nodes.get(edge.get("target"), {})
    if original.get("kind") != "bill" or alternative.get("kind") != "bill":
        return False
    numbers = [
        identifier.get("value")
        for identifier in original.get("identifiers", [])
        if identifier.get("namespace") == "ASSEMBLY_BILL_NUMBER"
        and isinstance(identifier.get("value"), str)
        and re.fullmatch(r"\d{7}", identifier["value"])
    ]
    texts = [
        proof.get("text")
        for proof in edge.get("evidence", [])
        if isinstance(proof, dict) and isinstance(proof.get("text"), str)
    ]
    title = alternative.get("name")
    return (
        len(numbers) == 1
        and bool(texts)
        and isinstance(title, str)
        and bool(title)
        and any(re.search(r"(?<!\d)" + numbers[0] + r"(?!\d)", text) for text in texts)
        and any(source_form(text, title) for text in texts)
        and any("대안" in text and ("통합" in text or "반영" in text) for text in texts)
    )


def audit_provenance(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Count structural proof defects in one private, consistent snapshot.

    Args:
        snapshot: Current sources, model control, and graph/community artifacts.

    Returns:
        Aggregate findings only. Passing does not establish political truth or
        authorize publishing unreviewed identities and relations.
    """
    graphs = select_snapshot_artifacts(snapshot, "graph")
    reports = select_snapshot_artifacts(snapshot, "community")
    units = {
        unit["id"]: (source, unit)
        for source in snapshot["sources"]
        for unit in source["payload"]["units"]
    }
    sources = {source["scope"]: source for source in snapshot["sources"]}
    by_child = {(item["kind"], item["key"]): item for item in graphs + reports}
    counts: Counter[str] = Counter()
    findings: Counter[str] = Counter()
    for graph in graphs:
        counts["graphs"] += 1
        if graph["payload"].get("public"):
            findings["unexpectedPublic"] += 1
        nodes = {node["id"]: node for node in graph["payload"]["nodes"]}
        dependencies = graph["dependency"].get("sources", [])
        bill_source = (
            sources.get(dependencies[0]["scope"]) if len(dependencies) == 1 else None
        )
        for edge in graph["payload"]["edges"]:
            counts["edges"] += 1
            if (
                bill_source
                and bill_source["payload"].get("document", {}).get("sourceKey")
                == "lawmaking-bill-detail"
                and edge["type"] in {"lead_sponsor", "co_sponsor"}
                and edge["target"] != bill_source["payload"].get("documentBillId")
            ):
                findings["billSponsorTargetMismatch"] += 1
            if edge["type"] == "incorporated_into_alternative":
                counts["lineageEdges"] += 1
                if not _lineage_evidence_complete(edge, nodes):
                    findings["lineageEvidenceIncomplete"] += 1
            if not valid_relation_endpoints(
                edge["type"],
                nodes.get(edge["source"], {}).get("kind", ""),
                nodes.get(edge["target"], {}).get("kind", ""),
            ):
                findings["invalidEdgeEndpoint"] += 1
            if edge.get(
                "documentIdentitySupported"
            ) and not _document_bill_identity_valid(graph, edge, nodes, sources):
                findings["documentIdentityMismatch"] += 1
            for proof in edge["evidence"]:
                counts["edgeProofs"] += 1
                if not _source_proof_valid(proof, units):
                    findings["edgeProofNotInSource"] += 1
    for report in reports:
        level = report["payload"]["level"]
        counts[f"reportsLevel{level}"] += 1
        if report["payload"].get("reportStatus") == "membership_only":
            counts[f"membershipOnlyLevel{level}"] += 1
        if report["payload"].get("public"):
            findings["unexpectedPublic"] += 1
        pinned = report["dependency"].get("children", [])
        children = [by_child.get((item["kind"], item["key"])) for item in pinned]
        if any(child is None for child in children):
            findings["missingChild"] += 1
            continue
        if any(
            child["version"] != item["version"]
            for child, item in zip(children, pinned, strict=True)
        ):
            findings["childVersionMismatch"] += 1
        if level == 0:
            expected = {
                node["id"] for child in children for node in child["payload"]["nodes"]
            }
            child_proofs = [
                proof
                for child in children
                for edge in child["payload"]["edges"]
                for proof in edge["evidence"]
            ]
        else:
            expected = {
                group["id"]
                for child in children
                for group in child["payload"]["groups"]
            }
            child_proofs = [
                claim["evidence"]
                for child in children
                for group in child["payload"]["groups"]
                for claim in group["claims"]
            ]
        members = [
            member
            for group in report["payload"]["groups"]
            for member in group["members"]
        ]
        if set(members) != expected or len(members) != len(set(members)):
            findings["membershipMismatch"] += 1
        for group in report["payload"]["groups"]:
            for claim in group["claims"]:
                counts["claims"] += 1
                proof = claim["evidence"]
                if not any(_proof_within(child, proof) for child in child_proofs):
                    findings["claimNotInChild"] += 1
                if not _source_proof_valid(proof, units):
                    findings["claimProofNotInSource"] += 1
    return {
        "schema": "parliament-graphrag-provenance-audit-v1",
        "public": False,
        "sourceUnits": len(units),
        "counts": dict(sorted(counts.items())),
        "findings": dict(sorted(findings.items())),
        "politicalTruthVerified": False,
    }
