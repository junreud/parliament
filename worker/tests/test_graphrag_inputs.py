"""Source identity and exact Unicode provenance survive incremental indexing."""

import json
from copy import deepcopy

import pytest

from parliament_worker.graphrag.inputs import sources_from_batch, split_interval
from parliament_worker.graphrag.prompts import extraction


def fixture_batch():
    text = "김가😀 의원은 새 법안을 대표발의했다."
    return {
        "id": "batch-test",
        "issueId": "issue-test",
        "entities": [
            {
                "id": "p-a",
                "kind": "person",
                "name": "김가",
                "identifiers": [{"namespace": "ASSEMBLY", "value": "1"}],
                "facts": [{"evidenceIds": ["ev-a"]}],
                "tenures": [],
            },
            {
                "id": "b-a",
                "kind": "bill",
                "name": "새 법안",
                "identifiers": [{"namespace": "BILL", "value": "2"}],
                "facts": [{"evidenceIds": ["ev-a"]}],
                "tenures": [],
            },
        ],
        "documents": [
            {
                "id": "doc-a",
                "sourceKey": "assembly",
                "recordKey": "2",
                "version": "version-a",
                "extractionVersion": "extract-a",
                "sourceUrl": "https://www.assembly.go.kr/example",
                "title": "법안",
                "licenseStatus": "unknown",
                "bodyStatus": "available",
                "segments": [
                    {
                        "id": "seg-a",
                        "locator": "html:p[1]",
                        "text": text,
                        "mentions": [],
                    }
                ],
            }
        ],
        "evidence": [
            {
                "id": "ev-a",
                "documentId": "doc-a",
                "documentVersion": "version-a",
                "extractionVersion": "extract-a",
                "segmentId": "seg-a",
                "start": 0,
                "end": len(text),
            }
        ],
        "relations": [],
        "activities": [],
        "contexts": [],
    }


def test_unknown_use_selects_only_fixed_evidence_and_keeps_pending():
    batch = fixture_batch()
    batch["documents"][0]["segments"].append(
        {
            "id": "contact",
            "text": "전화번호 비공개 개인정보",
            "locator": "p[2]",
            "mentions": [],
        }
    )
    source = sources_from_batch(batch)[0]
    assert len(source["payload"]["units"]) == 1
    assert (
        source["payload"]["units"][0]["text"] == "김가😀 의원은 새 법안을 대표발의했다."
    )
    assert source["payload"]["public"] is False
    assert source["scope"] == "assembly:2"
    assert {e["id"] for e in source["payload"]["entities"]} == {"p-a", "b-a"}


@pytest.mark.parametrize("license_status", ["unknown", "allowed"])
def test_contact_bearing_evidence_is_not_retained_for_inference(license_status):
    """Selected evidence cannot carry a phone number into model requests."""
    batch = fixture_batch()
    text = "김가 의원의 연락처는 010-1234-5678이다."
    batch["documents"][0]["licenseStatus"] = license_status
    batch["documents"][0]["segments"][0]["text"] = text
    batch["evidence"][0]["end"] = len(text)

    source = sources_from_batch(batch)[0]

    assert source["payload"]["units"] == []
    assert source["payload"]["bodyCoverage"] == "unavailable"
    assert source["payload"]["document"]["id"] == "doc-a"


def test_unknown_use_retains_exact_role_prefix_before_contact_field():
    """A selected office fact may retain its safe source prefix, not contact data."""
    batch = fixture_batch()
    text = "김가 농림축산식품부 장관으로 소개됐다. 연락처: 010-1234-5678"
    batch["documents"][0]["segments"][0]["text"] = text
    batch["evidence"][0]["end"] = len(text)
    batch["entities"][0]["facts"] = []
    batch["entities"][0]["tenures"] = [
        {
            "organizationId": "org-a",
            "position": "장관",
            "evidenceIds": ["ev-a"],
        }
    ]
    batch["entities"].append(
        {
            "id": "org-a",
            "kind": "organization",
            "name": "농림축산식품부",
            "identifiers": [],
            "facts": [],
            "tenures": [],
        }
    )

    source = sources_from_batch(batch)[0]["payload"]

    assert [unit["text"] for unit in source["units"]] == [
        "김가 농림축산식품부 장관으로 소개됐다."
    ]
    assert source["units"][0]["start"] == 0
    assert source["units"][0]["end"] == len(source["units"][0]["text"])
    assert source["bodyCoverage"] == "selected_evidence"


def test_unknown_use_retains_spaced_source_name_only_for_matching_person():
    """A source spelling may differ from the normalized name without merging IDs."""
    batch = fixture_batch()
    text = "현 수 엽 농림축산식품부 장관으로 소개됐다. 연락처: 010-1234-5678"
    document = batch["documents"][0]
    document["segments"][0]["text"] = text
    document["segments"][0]["mentions"] = [
        {
            "id": "mention-a",
            "surface": "현 수 엽",
            "start": 0,
            "end": len("현 수 엽"),
            "candidatePersonIds": ["p-a"],
            "personId": None,
            "decision": "pending",
        }
    ]
    batch["evidence"][0]["end"] = len(text)
    batch["entities"][0]["name"] = "현수엽"
    batch["entities"][0]["facts"] = []
    batch["entities"][0]["tenures"] = [
        {"organizationId": "org-a", "position": "장관", "evidenceIds": ["ev-a"]}
    ]
    batch["entities"].append(
        {
            "id": "org-a",
            "kind": "organization",
            "name": "농림축산식품부",
            "identifiers": [],
            "facts": [],
            "tenures": [],
        }
    )

    expected = "현 수 엽 농림축산식품부 장관으로 소개됐다."
    source = sources_from_batch(batch)[0]["payload"]
    assert [unit["text"] for unit in source["units"]] == [expected]
    assert source["units"][0]["end"] == len(expected)

    batch["entities"].append(
        {
            "id": "p-b",
            "kind": "person",
            "name": "다른 인물",
            "identifiers": [],
            "facts": [],
            "tenures": [],
        }
    )
    document["segments"][0]["mentions"][0]["candidatePersonIds"] = ["p-b"]
    assert sources_from_batch(batch)[0]["payload"]["units"] == []


def test_unknown_use_drops_contact_before_office_fact():
    """Never recover text beyond the first contact field in an evidence span."""
    batch = fixture_batch()
    text = "연락처: 010-1234-5678 김가 농림축산식품부 장관"
    batch["documents"][0]["segments"][0]["text"] = text
    batch["evidence"][0]["end"] = len(text)
    batch["entities"][0]["tenures"] = [
        {"organizationId": "org-a", "position": "장관", "evidenceIds": ["ev-a"]}
    ]
    batch["entities"].append(
        {
            "id": "org-a",
            "kind": "organization",
            "name": "농림축산식품부",
            "identifiers": [],
            "facts": [],
            "tenures": [],
        }
    )

    assert sources_from_batch(batch)[0]["payload"]["units"] == []


def test_official_activity_roles_keep_fixed_source_units_private():
    """A scheduled person and publishing agency remain source-bound candidates."""
    batch = fixture_batch()
    text = "성평등가족부는 김가 장관 주재 정책 간담회를 개최할 예정이다."
    document = batch["documents"][0]
    document["sourceKey"] = "ministry-press-release"
    document["recordKey"] = "briefing-1"
    document["sourceUrl"] = "https://www.mogef.go.kr/nw/rpd/example"
    document["segments"][0]["text"] = text
    batch["evidence"][0]["end"] = len(text)
    batch["entities"].append(
        {
            "id": "org-a",
            "kind": "organization",
            "name": "성평등가족부",
            "identifiers": [],
            "facts": [],
            "tenures": [],
        }
    )
    batch["activities"] = [
        {
            "id": "act-a",
            "title": "정책 간담회",
            "type": "announcement",
            "stage": "scheduled",
            "version": "activity-v1",
            "sourceUrl": document["sourceUrl"],
        }
    ]
    batch["relations"] = [
        {
            "id": f"relation-{subject_id}",
            "type": relation_type,
            "subjectId": subject_id,
            "objectId": "act-a",
            "evidenceIds": ["ev-a"],
            "decision": "pending",
        }
        for relation_type, subject_id in (
            ("publisher", "org-a"),
            ("scheduled_participant", "p-a"),
        )
    ]

    source = sources_from_batch(batch)[0]["payload"]

    assert source["public"] is False
    assert source["activityCandidates"] == [
        {
            "id": "act-a",
            "name": "정책 간담회",
            "type": "announcement",
            "stage": "scheduled",
            "version": "activity-v1",
        }
    ]
    assert source["activityRelationCandidates"] == [
        {
            "type": relation_type,
            "subjectId": subject_id,
            "objectId": "act-a",
            "unitIds": [source["units"][0]["id"]],
        }
        for relation_type, subject_id in (
            ("publisher", "org-a"),
            ("scheduled_participant", "p-a"),
        )
    ]


def test_observation_does_not_regenerate_but_extraction_and_identity_changes_do():
    batch = fixture_batch()
    before = sources_from_batch(batch)[0]["fingerprint"]
    batch["documents"][0]["observedAt"] = "2026-10-13"
    batch["id"] = "new-batch"
    assert sources_from_batch(batch)[0]["fingerprint"] == before
    batch["entities"][0]["name"] = "김나"
    assert sources_from_batch(batch)[0]["fingerprint"] != before
    modified = deepcopy(fixture_batch())
    modified["documents"][0]["extractionVersion"] = "extract-b"
    modified["evidence"][0]["extractionVersion"] = "extract-b"
    assert sources_from_batch(modified)[0]["fingerprint"] != before


def test_utf8_chunking_preserves_codepoint_intervals_without_omission():
    text = "A😀가" * 100
    parts = split_interval(text, 0, len(text), byte_limit=55)
    assert "".join(text[a:b] for a, b in parts) == text
    assert all(len(text[a:b].encode()) <= 55 for a, b in parts)
    assert parts[0][0] == 0 and parts[-1][1] == len(text)


def test_restricted_body_is_not_sent_and_missing_evidence_rejected():
    batch = fixture_batch()
    batch["documents"][0]["licenseStatus"] = "restricted"
    assert sources_from_batch(batch)[0]["payload"]["units"] == []
    batch = fixture_batch()
    batch["evidence"][0]["end"] = 1000
    with pytest.raises(ValueError):
        sources_from_batch(batch)


def test_partial_unknown_use_indexes_only_selected_evidence():
    batch = fixture_batch()
    document = batch["documents"][0]
    document["bodyStatus"] = "partial"
    document["segments"].append(
        {
            "id": "unselected",
            "locator": "pdf:page[3]",
            "text": "unselected page",
            "mentions": [],
        }
    )

    source = sources_from_batch(batch)[0]["payload"]

    assert [unit["text"] for unit in source["units"]] == [
        "김가😀 의원은 새 법안을 대표발의했다."
    ]
    assert source["bodyCoverage"] == "selected_evidence"


def test_partial_allowed_use_never_reports_full_coverage():
    batch = fixture_batch()
    document = batch["documents"][0]
    document["bodyStatus"] = "partial"
    document["licenseStatus"] = "allowed"

    source = sources_from_batch(batch)[0]["payload"]

    assert len(source["units"]) == 1
    assert source["bodyCoverage"] == "partial"


def test_extraction_only_offers_identified_bill_among_duplicate_titles():
    source = sources_from_batch(fixture_batch())[0]
    original = source["payload"]["entities"][1]
    original["identifiers"] = [{"namespace": "BILL", "value": "2200703"}]
    duplicate = {
        **original,
        "id": "b-other",
        "identifiers": [{"namespace": "BILL", "value": "2200987"}],
    }
    source["payload"]["entities"] = [
        source["payload"]["entities"][0],
        original,
        duplicate,
    ]
    unit = source["payload"]["units"][0]
    unit["text"] = "김가 의원의 새 법안 의안번호 2200703을 심사했다."
    unit["end"] = unit["start"] + len(unit["text"])

    body, context = extraction(source, unit)
    offered = json.loads(body["messages"][-1]["content"])["known"]

    assert {context["aliases"][item["id"]]["id"] for item in offered} == {"p-a", "b-a"}


def test_pending_bill_lineage_is_a_source_bound_candidate_not_an_edge():
    batch = fixture_batch()
    batch["entities"].append(
        {
            "id": "b-alt",
            "kind": "bill",
            "name": "새 법안(대안)",
            "identifiers": [{"namespace": "BILL", "value": "2204313"}],
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

    source = sources_from_batch(batch)[0]["payload"]

    assert source["relationCandidates"] == [
        {
            "type": "incorporated_into_alternative",
            "subjectId": "b-a",
            "objectId": "b-alt",
        }
    ]
    assert source["public"] is False
