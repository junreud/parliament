"""Structured bill candidates constrain model-inferred alternative links."""

from pathlib import Path

import pytest
from test_graphrag_inputs import fixture_batch

from parliament_worker.graphrag.index import source_dependency
from parliament_worker.graphrag.inputs import fingerprint, sources_from_batch
from parliament_worker.graphrag.lineage_safety import (
    audit_lineage_candidates,
    repair_lineage_candidates,
)
from parliament_worker.graphrag.store import GraphStore


def _store_with_false_lineage(
    tmp_path: Path, *, with_candidates: bool = True
) -> tuple[GraphStore, str]:
    store = GraphStore(tmp_path / "state")
    batch = fixture_batch()
    proof_text = (
        "원안 2200001 법안 대안 대안의 제안경위. "
        "위 1건을 통합하여 대안으로 제안한다."
    )
    batch["documents"][0]["segments"][0]["text"] = proof_text
    batch["evidence"][0]["end"] = len(proof_text)
    batch["entities"][1]["identifiers"] = [
        {"namespace": "ASSEMBLY_BILL_NUMBER", "value": "2200001"}
    ]
    for identifier, name in (("b-alt", "법안 대안"), ("b-other", "다른 원안")):
        batch["entities"].append(
            {
                "id": identifier,
                "kind": "bill",
                "name": name,
                "identifiers": (
                    [{"namespace": "ASSEMBLY_BILL_NUMBER", "value": "2200099"}]
                    if identifier == "b-alt"
                    else []
                ),
                "facts": [],
                "tenures": [],
            }
        )
    batch["relations"].append(
        {
            "id": "r-lineage",
            "type": "incorporated_into_alternative",
            "subjectId": "b-a",
            "objectId": "b-alt",
            "evidenceIds": ["ev-a"],
            "decision": "pending",
        }
    )
    source = sources_from_batch(batch)[0]
    if not with_candidates:
        source["payload"].pop("relationCandidates")
        source["fingerprint"] = fingerprint(source["payload"])
    store.put_sources([source])
    source = store.sources()[0]
    dependency = {"sources": [source_dependency(source)]}
    artifact_key = source["scope"] + ":unit-example"
    graph = {
        "nodes": [
            entity
            for entity in source["payload"]["entities"]
            if entity["kind"] == "bill"
        ],
        "edges": [
            {
                "id": edge_id,
                "source": "b-a",
                "target": target,
                "type": "incorporated_into_alternative",
                "evidence": [source["payload"]["units"][0]],
                "decision": "pending",
            }
            for edge_id, target in (("edge-good", "b-alt"), ("edge-bad", "b-other"))
        ],
        "public": False,
    }
    store.put_artifact("graph", artifact_key, dependency, graph)
    return store, artifact_key


def test_lineage_repair_preserves_proof_history_and_valid_link(tmp_path) -> None:
    """A false original-to-original edge is removed in a new graph version."""
    store, key = _store_with_false_lineage(tmp_path)
    initial = store.get_artifact("graph", key)
    report = audit_lineage_candidates(store)
    assert report["unsupportedEdges"] == 1
    assert report["affectedArtifacts"] == 1
    assert report["removedEdgeIds"] == ["edge-bad"]
    assert store.get_artifact("graph", key)["version"] == initial["version"]

    repaired = repair_lineage_candidates(store)
    current = store.get_artifact("graph", key)
    assert repaired["repairedArtifacts"] == 1
    assert [edge["id"] for edge in current["payload"]["edges"]] == ["edge-good"]
    assert current["version"] != initial["version"]
    assert len(store.artifact_versions("graph", key)) == 2
    assert repair_lineage_candidates(store)["repairedArtifacts"] == 0


def test_lineage_repair_waits_for_active_global_question(tmp_path) -> None:
    """A running global source snapshot is not invalidated mid-request."""
    store, _ = _store_with_false_lineage(tmp_path)
    store.put_artifact(
        "question",
        "question-running",
        {"sources": []},
        {"mode": "global", "state": "queued", "jobs": []},
    )
    with pytest.raises(ValueError, match="active global question"):
        repair_lineage_candidates(store)
    assert audit_lineage_candidates(store)["unsupportedEdges"] == 1


def test_lineage_repair_removes_unproven_pair_without_declared_candidates(
    tmp_path,
) -> None:
    """A bill's conditional passage cannot become an alternative lineage."""
    store, key = _store_with_false_lineage(tmp_path, with_candidates=False)
    initial = store.get_artifact("graph", key)

    assert audit_lineage_candidates(store)["removedEdgeIds"] == ["edge-bad"]
    report = repair_lineage_candidates(store)

    assert report["repairedArtifacts"] == 1
    assert len(store.artifact_versions("graph", key)) == 2
    assert store.get_artifact("graph", key)["version"] != initial["version"]
