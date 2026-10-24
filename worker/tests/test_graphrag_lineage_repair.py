"""Model-check cross-page alternative-bill links against fixed source units."""

import json
import time
from copy import deepcopy

import pytest
from test_graphrag_engine import SIGNATURE
from test_graphrag_inputs import fixture_batch

from parliament_worker.graphrag.engine import Factory
from parliament_worker.graphrag.inputs import sources_from_batch
from parliament_worker.graphrag.output_retries import plan_output_retries
from parliament_worker.graphrag.store import GraphStore


def lineage_source():
    """Build a two-page official-style extract with one pending relation."""
    batch = fixture_batch()
    original = batch["entities"][1]
    original.update(
        id="bill-original",
        name="양육비 법률안",
        identifiers=[{"namespace": "ASSEMBLY_BILL_NUMBER", "value": "2200703"}],
    )
    batch["entities"].append(
        {
            "id": "bill-alternative",
            "kind": "bill",
            "name": "양육비 법률안(대안)",
            "identifiers": [{"namespace": "ASSEMBLY_BILL_NUMBER", "value": "2204313"}],
            "facts": [],
            "tenures": [],
        }
    )
    first = "양육비 법률안(대안)\n1. 대안의 제안경위\n의안번호 2200703 심사경과"
    second = "위 1건의 법률안을 통합·조정하여 위원회 대안으로 제안하기로 함."
    document = batch["documents"][0]
    document["bodyStatus"] = "partial"
    document["segments"] = [
        {"id": "page-one", "locator": "pdf:page[1]", "text": first, "mentions": []},
        {"id": "page-two", "locator": "pdf:page[2]", "text": second, "mentions": []},
    ]
    batch["evidence"] = [
        {**batch["evidence"][0], "segmentId": "page-one", "end": len(first)},
        {
            **batch["evidence"][0],
            "id": "ev-b",
            "segmentId": "page-two",
            "end": len(second),
        },
    ]
    batch["relations"] = [
        {
            "id": "relation-lineage",
            "type": "incorporated_into_alternative",
            "subjectId": "bill-original",
            "objectId": "bill-alternative",
            "evidenceIds": ["ev-a", "ev-b"],
            "decision": "pending",
        }
    ]
    return sources_from_batch(batch)[0]


def test_cross_page_lineage_candidate_is_sent_once_to_the_model(tmp_path):
    store = GraphStore(tmp_path / "state")
    store.put_sources([lineage_source()])
    factory = Factory(store, None, SIGNATURE)

    factory.plan()
    factory.plan()

    lineage = [
        job
        for job in store.jobs()
        if job["context"].get("relation_task") == "bill_lineage"
    ]
    assert len(lineage) == 1
    job = lineage[0]
    prompt = json.loads(job["request"]["messages"][-1]["content"])
    assert prompt["candidate"]["originalNumber"] == "2200703"
    assert prompt["candidate"]["alternativeNumber"] == "2204313"
    assert set(prompt["source"]) == {"header", "decision", "row"}
    assert job["request"]["response_format"]["type"] == "json_schema"
    assert job["context"]["sources"][0]["scope"] == "assembly:2"


def completed_reply(supported):
    """Build a complete model response with the pinned test revision."""
    return {
        "state": "completed",
        "_modelMetadata": {
            "actual_model": "test-model",
            "revision": "test-revision",
        },
        "result": {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": json.dumps({"supported": supported})},
                }
            ]
        },
    }


def claimed_lineage(tmp_path):
    """Claim a prepared candidate without making an external HTTP call."""
    store = GraphStore(tmp_path / "state")
    store.put_sources([lineage_source()])
    factory = Factory(store, None, SIGNATURE)
    factory.plan()
    jobs = store.claim(factory.owner, lease_seconds=600, limit=10)
    job = next(item for item in jobs if item["context"].get("relation_task"))
    return factory, store.checkpoint(job["id"], factory.owner, state="submitting")


@pytest.mark.parametrize("supported", [True, False])
def test_lineage_response_keeps_cross_page_evidence_private(tmp_path, supported):
    factory, job = claimed_lineage(tmp_path)

    factory._complete(job, completed_reply(supported), time.time())

    graph = factory.store.get_artifact("graph", job["context"]["artifact_key"])
    assert graph is not None
    assert len(graph["payload"]["edges"]) == int(supported)
    if supported:
        edge = graph["payload"]["edges"][0]
        assert edge["type"] == "incorporated_into_alternative"
        assert edge["decision"] == "pending"
        assert {proof["locator"] for proof in edge["evidence"]} == {
            "pdf:page[1]",
            "pdf:page[2]",
        }
        assert graph["payload"]["public"] is False


def test_lineage_rejects_modified_source_unit_before_materialization(tmp_path):
    factory, job = claimed_lineage(tmp_path)
    tampered = deepcopy(job)
    tampered["context"]["units"]["decision"]["text"] += " 조작"

    with pytest.raises(ValueError, match="source proof"):
        factory._complete(tampered, completed_reply(True), time.time())

    assert factory.store.get_artifact("graph", job["context"]["artifact_key"]) is None


def test_lineage_output_retries_keep_the_boolean_contract(tmp_path):
    factory, job = claimed_lineage(tmp_path)
    factory.store.release(
        job["id"],
        factory.owner,
        state="failed",
        error="generated_content_validation_failed",
    )

    assert plan_output_retries(factory.store, SIGNATURE, 256) == 1
    retry = next(
        item
        for item in factory.store.jobs()
        if item["context"].get("retry_of") == job["id"]
    )
    factory.store.update_job(
        retry["id"], state="failed", error="generated_content_validation_failed"
    )
    assert (
        plan_output_retries(factory.store, SIGNATURE, 256, now=time.time() + 120) == 1
    )
    second = next(
        item
        for item in factory.store.jobs()
        if item["context"].get("retry_of") == retry["id"]
    )
    assert second["request"]["response_format"]["json_schema"]["name"] == "bill_lineage"
