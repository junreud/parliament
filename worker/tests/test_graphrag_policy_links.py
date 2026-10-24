"""Source-local bill and policy identities can reach grounded graph extraction."""

import json
from pathlib import Path

import pytest
from test_graphrag_inputs import fixture_batch

from parliament_worker.graphrag.inputs import sources_from_batch
from parliament_worker.graphrag.output_contract import directional_extraction_contract
from parliament_worker.graphrag.prompts import extraction, validate_extraction
from parliament_worker.knowledge.pipeline import validate_manifest
from parliament_worker.knowledge.review import validate_batch


def policy_batch():
    """One bill record that names a policy without repeating its bill number."""
    batch = fixture_batch()
    text = "이 법안은 양육비 선지급제에 관한 내용을 담았다."
    batch["issuePolicyId"] = "policy-advance"
    batch["entities"].append(
        {
            "id": "policy-advance",
            "kind": "policy",
            "name": "양육비 선지급제",
            "identifiers": [],
            "facts": [],
            "tenures": [],
        }
    )
    bill = batch["entities"][1]
    bill["identifiers"] = [{"namespace": "ASSEMBLY_BILL_NUMBER", "value": "2204313"}]
    bill["facts"] = []
    batch["documents"][0]["sourceKey"] = "lawmaking-bill-detail"
    batch["documents"][0]["recordKey"] = "2204313"
    batch["documents"][0]["segments"][0]["text"] = text
    batch["evidence"][0]["end"] = len(text)
    return batch


def test_explicit_issue_policy_and_bill_record_are_offered_for_model_relation():
    batch = policy_batch()
    source = sources_from_batch(batch)[0]
    assert {entity["id"] for entity in source["payload"]["entities"]} == {
        "p-a",
        "b-a",
        "policy-advance",
    }
    unit = source["payload"]["units"][0]
    body, context = extraction(source, unit)
    known = json.loads(body["messages"][-1]["content"])["known"]
    aliases = {entity["id"]: alias for alias, entity in context["aliases"].items()}
    assert {context["aliases"][item["id"]]["id"] for item in known} >= {
        "b-a",
        "policy-advance",
    }

    output = {
        "entities": [],
        "relations": [
            {
                "s": aliases["b-a"],
                "t": aliases["policy-advance"],
                "type": "concerns",
                "unit": "U1",
                "quote": unit["text"],
            }
        ],
    }
    edge = validate_extraction(output, context)["edges"][0]
    assert (edge["source"], edge["target"], edge["type"]) == (
        "b-a",
        "policy-advance",
        "concerns",
    )
    assert edge["evidence"][0]["documentId"] == "doc-a"
    assert edge["documentIdentitySupported"] is True


def test_unlinked_policy_or_wrong_bill_record_cannot_be_promoted():
    batch = policy_batch()
    batch["documents"][0]["recordKey"] = "2200703"
    source = sources_from_batch(batch)[0]
    assert "b-a" not in {entity["id"] for entity in source["payload"]["entities"]}

    batch = policy_batch()
    batch["issuePolicyId"] = "missing-policy"
    with pytest.raises(ValueError, match="invalid GraphRAG knowledge batch"):
        sources_from_batch(batch)


def test_policy_is_not_offered_when_selected_evidence_does_not_name_it():
    batch = policy_batch()
    batch["documents"][0]["segments"][0][
        "text"
    ] = "이 법안은 다른 안건에 관한 내용이다."
    batch["evidence"][0]["end"] = len(batch["documents"][0]["segments"][0]["text"])
    source = sources_from_batch(batch)[0]
    assert "policy-advance" not in {
        entity["id"] for entity in source["payload"]["entities"]
    }


def test_record_bound_relation_rejects_a_changed_bill_number():
    source = sources_from_batch(policy_batch())[0]
    unit = source["payload"]["units"][0]
    _, context = extraction(source, unit)
    aliases = {entity["id"]: alias for alias, entity in context["aliases"].items()}
    context["documentRecordKey"] = "2200703"

    with pytest.raises(ValueError, match="endpoint lacks quoted identity"):
        validate_extraction(
            {
                "entities": [],
                "relations": [
                    {
                        "s": aliases["b-a"],
                        "t": aliases["policy-advance"],
                        "type": "concerns",
                        "unit": "U1",
                        "quote": unit["text"],
                    }
                ],
            },
            context,
        )


def test_issue_policy_identity_must_be_an_explicit_policy_entity():
    manifest = json.loads(
        (Path(__file__).parents[1] / "examples/knowledge-fixture.json").read_text()
    )
    validate_manifest(manifest)
    manifest["issuePolicyId"] = "person-kim-miae"
    with pytest.raises(ValueError, match="issue policy"):
        validate_manifest(manifest)

    batch = policy_batch()
    validate_batch(batch)
    batch["issuePolicyId"] = "p-a"
    with pytest.raises(ValueError, match="issue policy"):
        validate_batch(batch)


def test_strict_retry_keeps_document_bound_bill_policy_candidate():
    source = sources_from_batch(policy_batch())[0]
    body, context = extraction(source, source["payload"]["units"][0])
    retry = directional_extraction_contract(body)
    schema = retry["response_format"]["json_schema"]["schema"]
    assert schema["properties"]["relations"]["maxItems"] > 0
    claims = schema["properties"]["relations"]["items"]["properties"]["claim"]["enum"]
    aliases = {entity["id"]: alias for alias, entity in context["aliases"].items()}
    assert f"concerns:{aliases['b-a']}>{aliases['policy-advance']}" in claims
