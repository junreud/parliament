"""New office candidates are compared with typed roster tenures before review."""

import json

from test_graphrag_inputs import fixture_batch

from parliament_worker.graphrag.inputs import sources_from_batch
from parliament_worker.graphrag.office_audit import (
    _review_proof,
    audit_office_edges,
    typed_office_pairs,
)
from parliament_worker.graphrag.store import GraphStore


def test_review_proof_reconstructs_only_contiguous_source_units():
    fixed = {
        "documentId": "doc-a",
        "documentVersion": "v1",
        "extractionVersion": "x1",
        "segmentId": "s1",
        "sourceUrl": "https://www.assembly.go.kr/example",
    }
    units = [
        {**fixed, "id": "u1", "start": 0, "end": 3, "text": "김가 "},
        {**fixed, "id": "u2", "start": 3, "end": 5, "text": "장관"},
    ]
    source = {"payload": {"units": units}}
    proof = {
        **fixed,
        "unitId": "joined",
        "sourceUnitIds": ["u1", "u2"],
        "start": 0,
        "end": 5,
        "text": "김가 장관",
    }

    assert _review_proof(proof, source)["exactMatch"] is True
    assert _review_proof(proof, source)["quote"] == "김가 장관"
    assert _review_proof({**proof, "text": "김가 의원"}, source)["exactMatch"] is False
    assert (
        _review_proof({**proof, "sourceUnitIds": ["u2", "u1"]}, source)["exactMatch"]
        is False
    )
    assert (
        _review_proof({**proof, "sourceUnitIds": [["u1"], "u2"]}, source)["exactMatch"]
        is False
    )


def test_review_proof_omits_contact_text_from_private_queue():
    text = "김가 장관 연락처 010-1234-5678"
    unit = {
        "id": "u1",
        "documentId": "doc-a",
        "documentVersion": "v1",
        "extractionVersion": "x1",
        "segmentId": "s1",
        "sourceUrl": "https://www.assembly.go.kr/example",
        "start": 0,
        "end": len(text),
        "text": text,
    }
    proof = {**unit, "unitId": "u1"}

    result = _review_proof(proof, {"payload": {"units": [unit]}})

    assert result["exactMatch"] is True
    assert result["contactOmitted"] is True
    assert result["quote"] is None


def test_office_audit_flags_unmatched_edges_without_approving_them(tmp_path):
    batch = fixture_batch()
    batch["entities"][0]["tenures"] = [
        {
            "organizationId": "org-a",
            "position": "위원",
            "evidenceIds": ["ev-a"],
        }
    ]
    for identifier, name in (("org-a", "의회"), ("org-party", "정당")):
        batch["entities"].append(
            {
                "id": identifier,
                "kind": "organization",
                "name": name,
                "identifiers": [],
                "facts": [],
                "tenures": [],
            }
        )
    input_path = tmp_path / "batch.json"
    input_path.write_text(json.dumps(batch, ensure_ascii=False))
    assert typed_office_pairs([input_path]) == {("p-a", "org-a")}
    store = GraphStore(tmp_path / "state")
    store.put_sources(sources_from_batch(batch))
    source = store.sources()[0]
    unit = source["payload"]["units"][0]
    nodes = [
        {"id": item["id"], "name": item["name"], "kind": item["kind"]}
        for item in batch["entities"]
    ]
    edges = [
        {
            "id": identifier,
            "source": "p-a",
            "target": target,
            "type": "holds_office",
            "decision": "pending",
            "evidence": [{"documentId": "doc-a", "unitId": unit["id"]}],
        }
        for identifier, target in (("edge-ok", "org-a"), ("edge-bad", "org-party"))
    ]
    edges[0]["evidence"] = [dict(unit, id="proof-ok", unitId=unit["id"])]
    store.put_artifact(
        "graph",
        source["scope"] + ":" + unit["id"],
        {
            "sources": [
                {key: source[key] for key in ("scope", "fingerprint", "generation")}
            ]
        },
        {"nodes": nodes, "edges": edges, "public": False},
    )

    report = audit_office_edges(store, [input_path])

    assert report["totalOfficeEdges"] == 2
    assert report["matchedTypedTenure"] == 1
    assert report["reviewRequired"] == 1
    assert report["missingTypedTenures"] == 0
    assert report["items"][0]["edgeId"] == "edge-bad"
    assert report["items"][0]["decision"] == "pending"
    assert all("text" not in item for item in report["items"])
    assert report["reviewQueueCount"] == 2
    reviewed = {item["edgeId"]: item for item in report["reviewQueue"]}
    assert reviewed["edge-ok"]["typedTenureMatched"] is True
    assert reviewed["edge-bad"]["typedTenureMatched"] is False
    assert all(item["decision"] == "pending" for item in reviewed.values())
    assert reviewed["edge-ok"]["evidence"][0]["exactMatch"] is True
    assert reviewed["edge-ok"]["evidence"][0]["quote"] == unit["text"]
    assert reviewed["edge-bad"]["evidence"][0]["exactMatch"] is False

    edges[0]["evidence"][0]["text"] = "원문에 없는 인용"
    store.put_artifact(
        "graph",
        source["scope"] + ":" + unit["id"],
        {
            "sources": [
                {key: source[key] for key in ("scope", "fingerprint", "generation")}
            ]
        },
        {"nodes": nodes, "edges": edges, "public": False},
    )
    tampered = audit_office_edges(store, [input_path])["reviewQueue"]
    invalid_proof = next(item for item in tampered if item["edgeId"] == "edge-ok")
    assert invalid_proof["evidence"][0]["exactMatch"] is False
    assert invalid_proof["evidence"][0]["quote"] is None

    store.put_artifact(
        "graph",
        source["scope"] + ":" + unit["id"],
        {
            "sources": [
                {key: source[key] for key in ("scope", "fingerprint", "generation")}
            ]
        },
        {"nodes": nodes, "edges": [], "public": False},
    )
    missing = audit_office_edges(store, [input_path])
    assert missing["missingTypedTenures"] == 1
    assert missing["missingItems"][0]["personId"] == "p-a"
    assert missing["missingItems"][0]["gapReason"] == "source_span_gap"
    assert missing["missingItems"][0]["sourceEvidence"][0]["unitCount"] == 1
    assert missing["missingItems"][0]["sourceEvidence"][0]["exactCoMention"] is False

    store.enqueue(
        "extract",
        "office-check",
        {},
        {
            "repair_version": "source-typed-list-office-v1",
            "aliases": {
                "E1": {"id": "p-a", "kind": "person"},
                "E2": {"id": "org-a", "kind": "organization"},
            },
        },
    )
    pending = audit_office_edges(store, [input_path])["missingItems"][0]
    assert pending["gapReason"] == "model_pending"

    store.put_artifact(
        "graph",
        source["scope"] + ":" + unit["id"],
        {
            "sources": [
                {key: source[key] for key in ("scope", "fingerprint", "generation")}
            ]
        },
        {"nodes": nodes, "edges": edges[:1], "public": False},
    )
    assert audit_office_edges(store, [input_path])["reviewRequired"] == 0


def test_office_gap_distinguishes_restricted_text_and_candidate_identity(tmp_path):
    batch = fixture_batch()
    batch["entities"][0]["tenures"] = [
        {"organizationId": "org-a", "position": "위원", "evidenceIds": ["ev-a"]}
    ]
    batch["entities"].append(
        {
            "id": "org-a",
            "kind": "organization",
            "name": "의회",
            "identifiers": [],
            "facts": [],
            "tenures": [],
        }
    )
    batch["documents"][0]["licenseStatus"] = "restricted"
    input_path = tmp_path / "batch.json"
    input_path.write_text(json.dumps(batch, ensure_ascii=False))
    store = GraphStore(tmp_path / "state")
    store.put_sources(sources_from_batch(batch))

    missing = audit_office_edges(store, [input_path])["missingItems"][0]
    assert missing["gapReason"] == "source_use_restricted"
    assert missing["sourceEvidence"][0]["unitCount"] == 0
    assert missing["alternateIdentityCandidates"] == []

    store.put_artifact(
        "graph",
        "alternate-source",
        {},
        {
            "nodes": [
                {"id": "p-alternate", "name": "김가", "kind": "person"},
                {"id": "org-other", "name": "의회", "kind": "organization"},
            ],
            "edges": [
                {
                    "id": "edge-alternate",
                    "source": "p-alternate",
                    "target": "org-other",
                    "type": "holds_office",
                    "evidence": [],
                    "decision": "pending",
                }
            ],
            "public": False,
        },
    )
    candidate = audit_office_edges(store, [input_path])["missingItems"][0]
    assert candidate["gapReason"] == "identity_review"
    assert candidate["alternateIdentityCandidates"] == [
        {
            "edgeId": "edge-alternate",
            "personId": "p-alternate",
            "organizationId": "org-other",
        }
    ]
