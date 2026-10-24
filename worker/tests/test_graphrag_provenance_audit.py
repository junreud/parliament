"""The private audit must follow shortened quotes and joined source units."""

from copy import deepcopy

from parliament_worker.graphrag.prompts import GROUP_ID_VERSION
from parliament_worker.graphrag.provenance_audit import (
    _source_proof_valid,
    audit_provenance,
)


def _snapshot():
    text = "사회민주당 대표"
    document = {
        "documentId": "doc-party",
        "documentVersion": "version-1",
        "extractionVersion": "extract-1",
        "segmentId": "segment-1",
        "sourceUrl": "https://example.go.kr/party",
    }
    units = [
        {"id": "unit-1", **document, "start": 0, "end": 4, "text": text[:4]},
        {"id": "unit-2", **document, "start": 4, "end": 8, "text": text[4:]},
    ]
    source = {
        "scope": "party:row-1",
        "fingerprint": "source-v1",
        "generation": 1,
        "payload": {"units": units},
    }
    dependency = {
        "sources": [
            {"scope": source["scope"], "fingerprint": "source-v1", "generation": 1}
        ]
    }
    composite = {
        **document,
        "id": "joined-1",
        "unitId": "joined-1",
        "sourceUnitIds": ["unit-1", "unit-2"],
        "start": 0,
        "end": 8,
        "text": text,
    }
    graph = {
        "kind": "graph",
        "key": "party:row-1:unit-1",
        "version": "graph-v1",
        "dependency": dependency,
        "payload": {
            "public": False,
            "nodes": [
                {"id": "person-1", "kind": "person", "name": "정당인"},
                {"id": "party-1", "kind": "organization", "name": "사회민주당"},
            ],
            "edges": [
                {
                    "id": "edge-1",
                    "type": "holds_office",
                    "source": "person-1",
                    "target": "party-1",
                    "evidence": [composite],
                }
            ],
        },
    }
    leaf = {
        "kind": "community",
        "key": "leaf-1",
        "version": "leaf-v1",
        "dependency": dependency
        | {
            "group_id_version": GROUP_ID_VERSION,
            "children": [
                {"kind": "graph", "key": graph["key"], "version": graph["version"]}
            ],
        },
        "payload": {
            "public": False,
            "level": 0,
            "groups": [
                {
                    "id": "group-1",
                    "members": ["person-1", "party-1"],
                    "claims": [
                        {
                            "text": "대표 근거",
                            "evidence": {
                                **composite,
                                "start": 6,
                                "end": 8,
                                "text": "대표",
                            },
                        }
                    ],
                }
            ],
        },
    }
    return {
        "sources": [source],
        "model": None,
        "artifacts": {"graph": [graph], "community": [leaf]},
    }


def test_audit_accepts_shorter_quote_from_joined_source_proof():
    result = audit_provenance(_snapshot())

    assert result["sourceUnits"] == 2
    assert result["counts"]["graphs"] == 1
    assert result["counts"]["reportsLevel0"] == 1
    assert result["counts"]["claims"] == 1
    assert result["findings"] == {}
    assert result["politicalTruthVerified"] is False


def test_audit_checks_document_bound_bill_identity_independently():
    snapshot = _snapshot()
    source = snapshot["sources"][0]
    source["payload"]["document"] = {
        "id": "doc-party",
        "sourceKey": "lawmaking-bill-detail",
        "recordKey": "2204313",
    }
    source["payload"]["documentBillId"] = "bill-2204313"
    graph = snapshot["artifacts"]["graph"][0]
    snapshot["artifacts"]["community"][0]["payload"]["groups"][0]["members"] = [
        "bill-2204313",
        "policy-advance",
    ]
    graph["payload"]["nodes"] = [
        {
            "id": "bill-2204313",
            "kind": "bill",
            "name": "법안",
            "identifiers": [{"namespace": "ASSEMBLY_BILL_NUMBER", "value": "2204313"}],
        },
        {"id": "policy-advance", "kind": "policy", "name": "대표"},
    ]
    edge = graph["payload"]["edges"][0]
    edge.update(
        type="concerns",
        source="bill-2204313",
        target="policy-advance",
        documentIdentitySupported=True,
    )
    assert audit_provenance(snapshot)["findings"] == {}

    source["payload"]["document"]["recordKey"] = "2200703"
    assert audit_provenance(snapshot)["findings"]["documentIdentityMismatch"] == 1


def test_audit_flags_sponsor_edge_to_a_nonrecord_bill_candidate():
    snapshot = _snapshot()
    source = snapshot["sources"][0]
    source["payload"]["document"] = {
        "id": "doc-party",
        "sourceKey": "lawmaking-bill-detail",
        "recordKey": "2204313",
    }
    source["payload"]["documentBillId"] = "bill-2204313"
    graph = snapshot["artifacts"]["graph"][0]
    graph["payload"]["nodes"] = [
        {"id": "person-1", "kind": "person", "name": "인물"},
        {"id": "bill-2204313", "kind": "bill", "name": "공식 의안"},
        {"id": "candidate-other-bill", "kind": "bill", "name": "다른 의안"},
    ]
    graph["payload"]["edges"][0].update(
        type="lead_sponsor", source="person-1", target="candidate-other-bill"
    )
    snapshot["artifacts"]["community"][0]["payload"]["groups"][0]["members"] = [
        "person-1",
        "bill-2204313",
        "candidate-other-bill",
    ]
    assert audit_provenance(snapshot)["findings"] == {"billSponsorTargetMismatch": 1}


def test_audit_rejects_wrong_quote_and_missing_member():
    snapshot = deepcopy(_snapshot())
    group = snapshot["artifacts"]["community"][0]["payload"]["groups"][0]
    group["members"].remove("party-1")
    group["claims"][0]["evidence"]["text"] = "불일치"

    result = audit_provenance(snapshot)

    assert result["findings"] == {
        "claimNotInChild": 1,
        "claimProofNotInSource": 1,
        "membershipMismatch": 1,
    }


def test_fixed_bill_lineage_quote_can_omit_inference_unit_id():
    source = _snapshot()["sources"][0]
    unit = source["payload"]["units"][0]
    proof = {key: value for key, value in unit.items() if key != "id"}
    units = {unit["id"]: (source, unit)}

    assert _source_proof_valid(proof, units) is True
    assert _source_proof_valid(proof | {"unitId": "wrong"}, units) is False


def test_bill_lineage_audit_requires_all_cross_page_relation_cues():
    snapshot = _snapshot()
    source = snapshot["sources"][0]
    source["payload"]["units"] = [
        {
            "id": f"unit-{index}",
            "documentId": "doc-bill",
            "documentVersion": "version-1",
            "extractionVersion": "extract-1",
            "segmentId": f"segment-{index}",
            "sourceUrl": "https://example.go.kr/bill",
            "start": 0,
            "end": len(text),
            "text": text,
        }
        for index, text in enumerate(
            (
                "양육비 법률안(대안) 대안의 제안경위",
                "원안 2201707 김미애의원",
                "위 8건을 통합하여 위원회 대안으로 제안",
            ),
            1,
        )
    ]
    graph = snapshot["artifacts"]["graph"][0]
    graph["payload"]["nodes"] = [
        {
            "id": "bill-original",
            "kind": "bill",
            "name": "원안",
            "identifiers": [{"namespace": "ASSEMBLY_BILL_NUMBER", "value": "2201707"}],
        },
        {
            "id": "bill-alternative",
            "kind": "bill",
            "name": "양육비 법률안(대안)",
            "identifiers": [{"namespace": "ASSEMBLY_BILL_NUMBER", "value": "2204313"}],
        },
    ]
    graph["payload"]["edges"] = [
        {
            "id": "lineage-edge",
            "type": "incorporated_into_alternative",
            "source": "bill-original",
            "target": "bill-alternative",
            "evidence": [
                {**unit, "unitId": unit["id"]} for unit in source["payload"]["units"]
            ],
        }
    ]
    snapshot["artifacts"]["community"] = []

    assert audit_provenance(snapshot)["findings"] == {}

    proofs = graph["payload"]["edges"][0]["evidence"]
    for missing in range(len(proofs)):
        graph["payload"]["edges"][0]["evidence"] = [
            proof for index, proof in enumerate(proofs) if index != missing
        ]
        assert audit_provenance(snapshot)["findings"] == {
            "lineageEvidenceIncomplete": 1
        }
