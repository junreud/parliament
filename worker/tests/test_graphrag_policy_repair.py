"""Targeted model checks fill missing bill-to-policy links from fixed records."""

import pytest
from test_graphrag_policy_links import policy_batch

from parliament_worker.graphrag.inputs import sources_from_batch
from parliament_worker.graphrag.output_retries import _next_request
from parliament_worker.graphrag.policy_repair import (
    plan_policy_links,
    validate_policy_link,
)
from parliament_worker.graphrag.store import GraphStore

MODEL = "test-model@test-revision"


def test_missing_bill_policy_pair_is_queued_once_and_stays_private(tmp_path):
    store = GraphStore(tmp_path / "state")
    store.put_sources(sources_from_batch(policy_batch()))

    assert plan_policy_links(store, MODEL, 16) == 1
    assert plan_policy_links(store, MODEL, 16) == 0
    job = next(
        j
        for j in store.jobs(kind="extract")
        if j["context"].get("relation_task") == "bill_policy"
    )
    source = store.sources()[0]
    graph = validate_policy_link({"supported": True}, job["context"], source)
    assert {node["id"] for node in graph["nodes"]} == {"b-a", "policy-advance"}
    assert len(graph["edges"]) == 1
    edge = graph["edges"][0]
    assert (edge["source"], edge["target"], edge["type"]) == (
        "b-a",
        "policy-advance",
        "concerns",
    )
    assert edge["documentIdentitySupported"] is True
    assert graph["public"] is False


def test_bill_policy_result_rejects_changed_document_identity(tmp_path):
    store = GraphStore(tmp_path / "state")
    store.put_sources(sources_from_batch(policy_batch()))
    assert plan_policy_links(store, MODEL, 16) == 1
    job = next(
        j
        for j in store.jobs(kind="extract")
        if j["context"].get("relation_task") == "bill_policy"
    )
    source = store.sources()[0]
    job["context"]["candidate"]["billNumber"] = "2200703"
    with pytest.raises(ValueError, match="bill policy"):
        validate_policy_link({"supported": True}, job["context"], source)


def test_bill_policy_retry_keeps_boolean_model_contract(tmp_path):
    store = GraphStore(tmp_path / "state")
    store.put_sources(sources_from_batch(policy_batch()))
    assert plan_policy_links(store, MODEL, 16) == 1
    job = next(
        j
        for j in store.jobs(kind="extract")
        if j["context"].get("relation_task") == "bill_policy"
    )
    job["error"] = "generated_content_validation_failed"
    request = _next_request(job, 2)
    assert request["response_format"]["json_schema"]["name"] == "bill_policy_relation"
