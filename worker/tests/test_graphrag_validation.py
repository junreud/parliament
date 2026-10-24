"""Untrusted model output never bypasses identity, source or role boundaries."""

import json

import pytest
from test_graphrag_inputs import fixture_batch

from parliament_worker.bill_feed import batch_from_bill_detail
from parliament_worker.graphrag.inputs import sources_from_batch
from parliament_worker.graphrag.prompts import (
    community_task,
    extraction,
    validate_extraction,
    validate_report,
)


def extracted():
    source = sources_from_batch(fixture_batch())[0]
    _, context = extraction(source, source["payload"]["units"][0])
    aliases = {e["kind"]: alias for alias, e in context["aliases"].items()}
    output = {
        "entities": [],
        "relations": [
            {
                "s": aliases["person"],
                "t": aliases["bill"],
                "type": "lead_sponsor",
                "unit": "U1",
                "quote": "김가😀 의원은 새 법안을 대표발의했다.",
            }
        ],
    }
    return output, context


def test_model_role_has_fixed_unicode_proof_and_needs_review():
    output, context = extracted()
    graph = validate_extraction(output, context)
    edge = graph["edges"][0]
    assert edge["source"] == "p-a" and edge["target"] == "b-a"
    assert edge["decision"] == "pending"
    assert edge["evidence"][0]["end"] == len("김가😀 의원은 새 법안을 대표발의했다.")


def test_official_bill_sponsor_must_target_the_record_bill():
    detail = {
        "title": "새 법률안",
        "proposal": "아무개의원 등 3인, 제2221909호",
        "summary": "새 제도를 제안한다.",
    }
    source = sources_from_batch(
        batch_from_bill_detail(
            "2221909", detail, b"official", "2026-10-16T12:00:00+09:00"
        )
    )[0]
    proposal = next(
        unit for unit in source["payload"]["units"] if "아무개" in unit["text"]
    )
    _, context = extraction(source, proposal)
    assert context["documentBillId"] == "bill-2221909"
    known_bill = next(
        alias
        for alias, item in context["aliases"].items()
        if item["id"] == "bill-2221909"
    )
    new_people = [
        {
            "id": "N1",
            "name": "아무개",
            "kind": "person",
            "unit": "U1",
            "quote": proposal["text"],
        }
    ]
    relation = {
        "s": "N1",
        "t": known_bill,
        "type": "lead_sponsor",
        "unit": "U1",
        "quote": proposal["text"],
    }
    accepted = validate_extraction(
        {"entities": new_people, "relations": [relation]}, context
    )
    assert accepted["edges"][0]["target"] == "bill-2221909"
    with pytest.raises(ValueError, match="record bill"):
        validate_extraction(
            {
                "entities": new_people
                + [
                    {
                        "id": "N2",
                        "name": "제2221909호",
                        "kind": "bill",
                        "unit": "U1",
                        "quote": proposal["text"],
                    }
                ],
                "relations": [relation | {"t": "N2"}],
            },
            context,
        )


def test_lineage_extraction_ignores_undeclared_original_to_original_links():
    """Adjacent original bills in a committee table are not each other's alternative."""
    text = "원안1 2200001 원안2 2200002 통합하여 대안 2200099 제안"
    entities = [
        {
            "id": identifier,
            "kind": "bill",
            "name": name,
            "identifiers": [{"namespace": "ASSEMBLY_BILL_NUMBER", "value": number}],
        }
        for identifier, name, number in (
            ("bill-a", "원안1", "2200001"),
            ("bill-b", "원안2", "2200002"),
            ("bill-alt", "대안", "2200099"),
        )
    ]
    unit = {
        "id": "unit-lineage",
        "documentId": "doc-lineage",
        "documentVersion": "v1",
        "extractionVersion": "x1",
        "segmentId": "segment-lineage",
        "sourceUrl": "https://example.org/committee",
        "locator": "pdf:page[1]",
        "licenseStatus": "unknown",
        "start": 0,
        "end": len(text),
        "text": text,
    }
    source = {
        "payload": {
            "entities": entities,
            "units": [unit],
            "relationCandidates": [
                {
                    "type": "incorporated_into_alternative",
                    "subjectId": "bill-a",
                    "objectId": "bill-alt",
                }
            ],
        }
    }
    _, context = extraction(source, unit)
    alias = {value["id"]: key for key, value in context["aliases"].items()}
    output = {
        "entities": [],
        "relations": [
            {
                "s": alias[subject],
                "t": alias[target],
                "type": "incorporated_into_alternative",
                "unit": "U1",
                "quote": text,
            }
            for subject, target in (("bill-a", "bill-alt"), ("bill-a", "bill-b"))
        ],
    }

    assert context["allowedLineagePairs"] == [["bill-a", "bill-alt"]]
    graph = validate_extraction(output, context)
    assert [(edge["source"], edge["target"]) for edge in graph["edges"]] == [
        ("bill-a", "bill-alt")
    ]
    source["payload"].pop("relationCandidates")
    _, context_without_candidate = extraction(source, unit)
    assert context_without_candidate["allowedLineagePairs"] == []
    assert validate_extraction(output, context_without_candidate)["edges"] == []


@pytest.mark.parametrize("relation_type", ["speaker", "records"])
def test_role_with_wrong_endpoint_kinds_is_rejected(relation_type):
    output, context = extracted()
    output["relations"][0]["type"] = relation_type
    with pytest.raises(ValueError, match="relation endpoints"):
        validate_extraction(output, context)


def test_extraction_does_not_offer_roles_without_activity_or_document_nodes():
    source = sources_from_batch(fixture_batch())[0]
    body, _ = extraction(source, source["payload"]["units"][0])
    offered = json.loads(body["messages"][1]["content"])["types"]
    assert {"speaker", "voter", "scheduled_participant", "records"}.isdisjoint(offered)
    assert "holds_office" in offered


@pytest.mark.parametrize("mutation", ["quote", "identity", "role", "endpoint"])
def test_invented_reference_or_role_rejected(mutation):
    output, context = extracted()
    item = output["relations"][0]
    if mutation == "quote":
        item["quote"] = "존재하지 않는 말"
    if mutation == "identity":
        item["s"] = "E99"
    if mutation == "role":
        item["type"] = "policy_credit"
    if mutation == "endpoint":
        item["s"], item["t"] = item["t"], item["s"]
    with pytest.raises(ValueError):
        validate_extraction(output, context)


def test_new_same_name_never_merges_with_known_identity():
    output, context = extracted()
    output["entities"] = [
        {"id": "N1", "name": "김가", "kind": "person", "unit": "U1", "quote": "김가😀"}
    ]
    graph = validate_extraction(output, context)
    assert len([node for node in graph["nodes"] if node["name"] == "김가"]) == 2
    assert [node for node in graph["nodes"] if node["identityStatus"] == "pending"][0][
        "id"
    ].startswith("candidate_")


def test_community_partition_requires_all_members_and_grounded_claims():
    output, context = extracted()
    graph = validate_extraction(output, context)
    _, context = community_task(graph["nodes"], graph["edges"][0]["evidence"], level=0)
    answer = {
        "groups": [
            {
                "title": "양육 정책",
                "members": list(context["aliases"]),
                "summary": "법안 발의 기록",
                "claims": [
                    {
                        "text": "김가의 대표발의 기록",
                        "unit": "S1",
                        "quote": "대표발의했다.",
                    }
                ],
            }
        ]
    }
    result = validate_report(answer, context)
    assert (
        result["groups"][0]["claims"][0]["evidence"]["documentVersion"] == "version-a"
    )
    answer["groups"][0]["members"].pop()
    with pytest.raises(ValueError):
        validate_report(answer, context)


def test_prose_without_source_cannot_become_a_report():
    _, context = community_task(
        [{"id": "p", "name": "김가", "kind": "person"}], [], level=0
    )
    with pytest.raises(ValueError):
        validate_report(
            {
                "groups": [
                    {
                        "title": "인물",
                        "members": ["E1"],
                        "summary": "성과를 냈다",
                        "claims": [],
                    }
                ]
            },
            context,
        )


@pytest.mark.parametrize(
    ("claim_text", "source_text"),
    [
        ("E1이 간담회를 개최할 예정임.", "원민경 장관은 간담회를 개최할 예정이다."),
        ("원민경 장관이 간담회를 주재함.", "원민경 장관 주재로 간담회를 개최한다."),
    ],
)
def test_community_report_rejects_misleading_claim_before_projection(
    claim_text: str, source_text: str
) -> None:
    """A generated report with an internal alias or false completion fails."""
    context = {
        "aliases": {"E1": {"id": "person-1"}},
        "units": {"S1": {"id": "unit-1", "text": source_text, "start": 0}},
        "level": 0,
    }
    output = {
        "groups": [
            {
                "title": "간담회",
                "members": ["E1"],
                "summary": claim_text,
                "claims": [{"text": claim_text, "unit": "S1", "quote": source_text}],
            }
        ]
    }

    with pytest.raises(ValueError, match="community claim quality"):
        validate_report(output, context)


def test_community_request_explicitly_preserves_names_and_event_tense() -> None:
    """The first request tells the model how to avoid observed prose errors."""
    source_text = "원민경 장관 주재로 간담회를 개최한다."
    body, _ = community_task(
        [{"id": "person-1", "name": "원민경", "kind": "person"}],
        [{"id": "unit-1", "text": source_text, "start": 0}],
        level=0,
    )
    rules = json.loads(body["messages"][-1]["content"])["rules"]

    assert "E1" in rules
    assert "names" in rules
    assert "scheduled" in rules
    assert "completed" in rules
