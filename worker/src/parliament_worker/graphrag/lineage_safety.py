"""Reconcile inferred bill lineage against source candidates and fixed proof."""

from typing import Any

from parliament_worker.graphrag.index import current_artifacts, source_dependency
from parliament_worker.graphrag.provenance_audit import _lineage_evidence_complete
from parliament_worker.graphrag.query import question_status
from parliament_worker.graphrag.store import GraphStore

LINEAGE = "incorporated_into_alternative"


def _changes(
    store: GraphStore,
) -> list[tuple[dict[str, Any], list[dict[str, Any]], list[str]]]:
    sources = {source["scope"]: source for source in store.sources()}
    changes = []
    for artifact in current_artifacts(store, "graph"):
        dependencies = artifact["dependency"].get("sources", [])
        if len(dependencies) != 1:
            continue
        source = sources.get(dependencies[0].get("scope"))
        if source is None or dependencies != [source_dependency(source)]:
            continue
        allowed = {
            (candidate["subjectId"], candidate["objectId"])
            for candidate in source["payload"].get("relationCandidates", [])
            if candidate["type"] == LINEAGE
        }
        has_candidates = "relationCandidates" in source["payload"]
        nodes = {node["id"]: node for node in artifact["payload"].get("nodes", [])}
        kept, removed = [], []
        for edge in artifact["payload"].get("edges", []):
            if edge["type"] == LINEAGE and (
                not _lineage_evidence_complete(edge, nodes)
                or (has_candidates and (edge["source"], edge["target"]) not in allowed)
            ):
                removed.append(edge["id"])
            else:
                kept.append(edge)
        if removed:
            changes.append((artifact, kept, removed))
    return changes


def _report(
    changes: list[tuple[dict[str, Any], list[dict[str, Any]], list[str]]],
) -> dict[str, Any]:
    return {
        "schema": "parliament-graphrag-lineage-safety-v1",
        "affectedArtifacts": len(changes),
        "unsupportedEdges": sum(len(removed) for _, _, removed in changes),
        "removedEdgeIds": sorted(
            edge_id for _, _, removed in changes for edge_id in removed
        ),
        "private": True,
        "publicationApproved": False,
    }


def audit_lineage_candidates(store: GraphStore) -> dict[str, Any]:
    """List unsupported or unproven links without modifying graph history.

    Args:
        store: Private GraphRAG state with source-bound relation candidates.

    Returns:
        Text-free edge identifiers requiring removal from current graph versions.
    """
    return _report(_changes(store))


def repair_lineage_candidates(store: GraphStore) -> dict[str, Any]:
    """Version corrected graph leaves after active global questions finish.

    Args:
        store: Private GraphRAG state to repair.

    Returns:
        Audit counts and the number of new current graph versions.

    Raises:
        ValueError: If a global question is still using the current graph or an
            artifact changed while repair was being prepared.
    """
    for question in store.artifacts("question"):
        if question["payload"].get("mode") != "global":
            continue
        state = (
            question_status(store, question["key"])["state"]
            if "snapshot" in question["payload"]
            else question["payload"].get("state")
        )
        if state == "queued":
            raise ValueError("active global question must finish before lineage repair")
    changes = _changes(store)
    report = _report(changes)
    repaired = 0
    for artifact, kept, _ in changes:
        current = store.get_artifact("graph", artifact["key"])
        if current is None or current["version"] != artifact["version"]:
            raise ValueError("graph artifact changed during lineage repair")
        store.put_artifact(
            "graph",
            artifact["key"],
            artifact["dependency"],
            {**artifact["payload"], "edges": kept},
        )
        repaired += 1
    return {**report, "repairedArtifacts": repaired}
