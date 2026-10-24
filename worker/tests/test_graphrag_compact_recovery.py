"""Compact extraction avoids repeated quotes and invalid self links."""

import json

import pytest
from test_graphrag_engine import SIGNATURE, RemoteFixture, make_factory

from parliament_worker.graphrag import output_contract, output_retries
from parliament_worker.graphrag.engine import Factory
from parliament_worker.graphrag.index import source_dependency
from parliament_worker.graphrag.inputs import fingerprint
from parliament_worker.graphrag.output_retries import plan_output_retries
from parliament_worker.graphrag.prompts import (
    GROUP_ID_VERSION,
    PROMPT_VERSION,
    community_task,
    extraction,
    valid_relation_endpoints,
    validate_extraction,
    validate_report,
)


def test_compact_contract_requires_distinct_endpoint_pair_without_repeated_quote(
    tmp_path,
):
    _, source = make_factory(tmp_path)
    body, _ = extraction(source, source["payload"]["units"][0])
    compact = output_contract.compact_extraction_contract(body)
    schema = compact["response_format"]["json_schema"]["schema"]
    relation = schema["properties"]["relations"]["items"]
    entity = schema["properties"]["entities"]["items"]
    assert set(relation["required"]) == {"pair", "type", "unit"}
    assert set(entity["required"]) == {"id", "name", "kind", "unit"}
    assert all(
        left != right
        for value in relation["properties"]["pair"]["enum"]
        for left, right in [value.split(">")]
    )
    assert all(
        not value.startswith("N") and ">N" not in value
        for value in relation["properties"]["pair"]["enum"]
    )
    assert "quote" not in json.dumps(schema)
    names = entity["properties"]["name"]["enum"]
    source_text = source["payload"]["units"][0]["text"]
    assert names and all(name in source_text for name in names)
    assert compact["max_completion_tokens"] <= 1024


def test_compact_output_restores_exact_unit_and_retains_validator(tmp_path):
    _, source = make_factory(tmp_path)
    _, context = extraction(source, source["payload"]["units"][0])
    aliases = {item["kind"]: key for key, item in context["aliases"].items()}
    pair = aliases["person"] + ">" + aliases["bill"]
    restored = output_contract.materialize_compact_extraction(
        {
            "entities": [],
            "relations": [{"pair": pair, "type": "lead_sponsor", "unit": "U1"}],
        },
        context,
    )
    assert restored["relations"][0]["quote"] == context["units"]["U1"]["text"]
    assert validate_extraction(restored, context)["edges"]
    with pytest.raises(ValueError, match="pair"):
        output_contract.materialize_compact_extraction(
            {
                "entities": [],
                "relations": [
                    {
                        "pair": aliases["person"] + ">" + aliases["person"],
                        "type": "records",
                        "unit": "U1",
                    }
                ],
            },
            context,
        )
    with pytest.raises(ValueError, match="pair"):
        output_contract.materialize_compact_extraction(
            {
                "entities": [],
                "relations": [
                    {"pair": aliases["person"] + ">N1", "type": "records", "unit": "U1"}
                ],
            },
            context,
        )


def test_repeated_failed_extraction_switches_to_directional_compact_version(tmp_path):
    factory, source = make_factory(tmp_path)
    source = factory.store.sources()[0]
    unit = source["payload"]["units"][0]
    body, context = extraction(source, unit)
    context.update(
        sources=[source_dependency(source)],
        artifact_key=source["scope"] + ":" + unit["id"],
        model_signature=SIGNATURE,
        prompt_version=PROMPT_VERSION,
        retry_of="earlier-failed-job",
    )
    job_id = factory.store.enqueue("extract", fingerprint(["failed-v2"]), body, context)
    factory.store.update_job(
        job_id, state="failed", error="generated_content_validation_failed"
    )
    failed_at = factory.store.get_job(job_id)["updated_at"]
    assert plan_output_retries(factory.store, SIGNATURE, 256, now=failed_at) == 1
    new = factory.store.jobs()[-1]
    assert new["context"]["output_contract"] == output_contract.DIRECTIONAL_CONTRACT
    relation = new["request"]["response_format"]["json_schema"]["schema"]["properties"][
        "relations"
    ]["items"]
    assert "claim" in relation["properties"]
    assert new["request"]["max_completion_tokens"] <= 1024


def test_repeated_name_uses_unique_local_evidence_span(tmp_path):
    _, source = make_factory(tmp_path)
    _, context = extraction(source, source["payload"]["units"][0])
    text = "안내 양육비이행관리원 누리집. 접수 양육비이행관리원 방문."
    context["units"]["U1"] = {**context["units"]["U1"], "text": text}
    restored = output_contract.materialize_compact_extraction(
        {
            "entities": [
                {
                    "id": "N1",
                    "name": "양육비이행관리원",
                    "kind": "organization",
                    "unit": "U1",
                }
            ],
            "relations": [],
        },
        context,
    )
    quote = restored["entities"][0]["quote"]
    assert text.count(quote) == 1
    assert quote.count("양육비이행관리원") == 1
    assert validate_extraction(restored, context)["nodes"]


def test_factory_projects_valid_compact_response_with_original_evidence(tmp_path):
    factory, _ = make_factory(tmp_path)
    source = factory.store.sources()[0]
    unit = source["payload"]["units"][0]
    body, context = extraction(source, unit)
    aliases = {item["kind"]: key for key, item in context["aliases"].items()}
    context.update(
        sources=[source_dependency(source)],
        artifact_key=source["scope"] + ":" + unit["id"],
        model_signature=SIGNATURE,
        prompt_version=PROMPT_VERSION,
        output_contract=output_contract.COMPACT_CONTRACT,
    )
    job_id = factory.store.enqueue(
        "extract",
        fingerprint(["compact-factory"]),
        output_contract.compact_extraction_contract(body),
        context,
    )
    remote = RemoteFixture()
    compact = {
        "entities": [],
        "relations": [
            {
                "pair": aliases["person"] + ">" + aliases["bill"],
                "type": "lead_sponsor",
                "unit": "U1",
            }
        ],
    }
    remote.poll = lambda _: {
        "state": "completed",
        "_modelMetadata": remote.model,
        "result": {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": json.dumps(compact, ensure_ascii=False),
                    },
                }
            ]
        },
    }
    running = Factory(factory.store, remote, SIGNATURE, poll_seconds=0.1)
    running.tick(1)
    factory.store.update_job(job_id, next_poll=0)
    running.tick(1)
    assert factory.store.get_job(job_id)["state"] == "completed"
    graph = factory.store.get_artifact("graph", context["artifact_key"])
    assert graph and graph["payload"]["edges"][0]["evidence"][0]["text"] == unit["text"]


def test_retry_scheduler_leaves_storage_headroom(tmp_path, monkeypatch):
    factory, _ = make_factory(tmp_path)
    source = factory.store.sources()[0]
    unit = source["payload"]["units"][0]
    body, context = extraction(source, unit)
    context.update(
        sources=[source_dependency(source)],
        artifact_key=source["scope"] + ":" + unit["id"],
        model_signature=SIGNATURE,
        prompt_version=PROMPT_VERSION,
    )
    job_id = factory.store.enqueue(
        "extract", fingerprint(["storage-limit"]), body, context
    )
    factory.store.update_job(
        job_id, state="failed", error="generated_content_validation_failed"
    )
    monkeypatch.setattr(
        output_retries,
        "MAX_SNAPSHOT_BYTES",
        factory.store.database.stat().st_size + 7_000_000,
    )
    assert plan_output_retries(factory.store, SIGNATURE, 256) == 0
    assert len(factory.store.jobs()) == 1


def test_repeated_community_failure_allows_every_member_a_group(tmp_path):
    factory, _ = make_factory(tmp_path)
    members = [
        {"id": f"person-{i}", "name": f"인물{i}", "kind": "person"} for i in range(4)
    ]
    body, context = community_task(members, [{"text": "공식 발표 기록"}], level=0)
    context.update(
        sources=[],
        children=[],
        group_id_version=GROUP_ID_VERSION,
        artifact_key="community-four-members",
        model_signature=SIGNATURE,
        prompt_version=PROMPT_VERSION,
        retry_of="older-attempt",
    )
    job_id = factory.store.enqueue(
        "community", fingerprint(["community-retry"]), body, context
    )
    factory.store.update_job(
        job_id, state="failed", error="generated_content_validation_failed"
    )
    failed_at = factory.store.get_job(job_id)["updated_at"]
    assert plan_output_retries(factory.store, SIGNATURE, 256, now=failed_at) == 1
    retry = factory.store.jobs()[-1]
    assert (
        retry["context"]["output_contract"]
        == output_contract.COMPLETE_COMMUNITY_CONTRACT
    )
    schema = retry["request"]["response_format"]["json_schema"]["schema"]
    assert schema["properties"]["groups"]["maxItems"] == 4
    rules = json.loads(retry["request"]["messages"][-1]["content"])["rules"]
    assert all(f"E{i}" in rules for i in range(1, 5))
    groups = [
        {"title": f"인물{i}", "members": [f"E{i}"], "summary": "", "claims": []}
        for i in range(1, 5)
    ]
    assert len(validate_report({"groups": groups}, retry["context"])["groups"]) == 4


def test_persistent_community_failure_gets_precise_evidence_retry(tmp_path):
    factory, _ = make_factory(tmp_path)
    members = [
        {"id": f"person-{i}", "name": f"인물{i}", "kind": "person"} for i in range(3)
    ]
    body, context = community_task(members, [{"text": "공식 발표 기록"}], level=1)
    context.update(
        sources=[],
        children=[],
        group_id_version=GROUP_ID_VERSION,
        artifact_key="persistent-community",
        model_signature=SIGNATURE,
        prompt_version=PROMPT_VERSION,
        output_contract=output_contract.COMPLETE_COMMUNITY_CONTRACT,
        retry_attempt=3,
    )
    job_id = factory.store.enqueue(
        "community", fingerprint(["persistent-community", 3]), body, context
    )
    factory.store.update_job(
        job_id, state="failed", error="generated_content_validation_failed"
    )
    failed_at = factory.store.get_job(job_id)["updated_at"]
    assert plan_output_retries(factory.store, SIGNATURE, 256, now=failed_at) == 1
    retry = factory.store.jobs()[-1]
    assert retry["context"]["retry_attempt"] == 4
    assert (
        retry["context"]["output_contract"]
        == output_contract.PRECISE_COMMUNITY_CONTRACT
    )
    rules = json.loads(retry["request"]["messages"][-1]["content"])["rules"]
    assert "E1, E2, E3" in rules
    assert "unique exact contiguous substring" in rules
    assert "claims=[]" in rules
    assert retry["request"]["response_format"]["json_schema"]["name"] == (
        "parliament_community_precise_v4"
    )
    assert retry["context"]["units"] == context["units"]
    groups = [
        {"title": f"인물{i}", "members": [f"E{i}"], "summary": "", "claims": []}
        for i in range(1, 4)
    ]
    assert len(validate_report({"groups": groups}, retry["context"])["groups"]) == 3


def test_repeated_invalid_report_uses_model_partition_without_claims(tmp_path):
    factory, _ = make_factory(tmp_path)
    members = [
        {"id": f"person-{i}", "name": f"인물{i}", "kind": "person"} for i in range(3)
    ]
    body, context = community_task(members, [{"text": "공식 발표 기록"}], level=1)
    context.update(
        sources=[],
        children=[],
        group_id_version=GROUP_ID_VERSION,
        artifact_key="assignment-recovery",
        model_signature=SIGNATURE,
        prompt_version=PROMPT_VERSION,
        output_contract=output_contract.PRECISE_COMMUNITY_CONTRACT,
        retry_attempt=5,
    )
    job_id = factory.store.enqueue(
        "community", fingerprint(["assignment-recovery"]), body, context
    )
    factory.store.update_job(
        job_id, state="failed", error="generated_content_validation_failed"
    )
    failed_at = factory.store.get_job(job_id)["updated_at"]
    assert plan_output_retries(factory.store, SIGNATURE, 256, now=failed_at) == 1
    retry = factory.store.jobs()[-1]
    assert retry["context"]["retry_attempt"] == 6
    assert retry["context"]["output_contract"] == (
        output_contract.ASSIGNMENT_COMMUNITY_CONTRACT
    )
    schema = retry["request"]["response_format"]["json_schema"]["schema"]
    assignments = schema["properties"]["assignments"]
    assert set(assignments["required"]) == {"E1", "E2", "E3"}
    assert assignments["additionalProperties"] is False
    from parliament_worker.graphrag.community_retry import materialize_partition

    result = materialize_partition(
        {"assignments": {"E1": 0, "E2": 0, "E3": 1}}, retry["context"]
    )
    validated = validate_report(result, retry["context"])
    assert len(validated["groups"]) == 2
    assert {m for group in validated["groups"] for m in group["members"]} == {
        "person-0",
        "person-1",
        "person-2",
    }
    assert all(group["claims"] == [] for group in validated["groups"])
    assert all(group["summary"] == "" for group in validated["groups"])
    with pytest.raises(ValueError):
        materialize_partition({"assignments": {"E1": 0}}, retry["context"])


def test_oversized_community_request_retries_with_bounded_assignment(tmp_path):
    factory, _ = make_factory(tmp_path)
    members = [
        {
            "id": f"person-{i}",
            "name": f"인물{i}",
            "kind": "person",
            "summary": "긴 소개" * 25,
        }
        for i in range(3)
    ]
    body, context = community_task(members, [{"text": "긴 공식 자료" * 20}], level=1)
    context.update(
        sources=[],
        children=[],
        group_id_version=GROUP_ID_VERSION,
        artifact_key="oversized-community",
        model_signature=SIGNATURE,
        prompt_version=PROMPT_VERSION,
    )
    job_id = factory.store.enqueue(
        "community", fingerprint(["oversized-community"]), body, context
    )
    factory.store.update_job(
        job_id, state="failed", error="inference_request_context_limit"
    )
    failed_at = factory.store.get_job(job_id)["updated_at"]
    assert plan_output_retries(factory.store, SIGNATURE, 256, now=failed_at) == 1
    retry = factory.store.jobs()[-1]
    assert retry["context"]["output_contract"] == (
        output_contract.ASSIGNMENT_COMMUNITY_CONTRACT
    )
    payload = json.loads(retry["request"]["messages"][-1]["content"])
    assert retry["request"]["max_completion_tokens"] == 128
    assert all(len(text) <= 120 for text in payload["sources"].values())
    assert all(len(member.get("summary", "")) <= 120 for member in payload["members"])
    assert context["units"]["S1"]["text"] == "긴 공식 자료" * 20


def test_directional_contract_encodes_only_valid_role_endpoints(tmp_path):
    _, source = make_factory(tmp_path)
    body, context = extraction(source, source["payload"]["units"][0])
    aliases = {item["kind"]: key for key, item in context["aliases"].items()}
    request = output_contract.directional_extraction_contract(body)
    assert output_contract.directional_extraction_contract(request) == request
    relation = request["response_format"]["json_schema"]["schema"]["properties"][
        "relations"
    ]["items"]
    choices = relation["properties"]["claim"]["enum"]
    assert "lead_sponsor:" + aliases["person"] + ">" + aliases["bill"] in choices
    assert "lead_sponsor:" + aliases["bill"] + ">" + aliases["person"] not in choices
    restored = output_contract.materialize_compact_extraction(
        {
            "entities": [],
            "relations": [
                {
                    "claim": "lead_sponsor:"
                    + aliases["person"]
                    + ">"
                    + aliases["bill"],
                    "unit": "U1",
                }
            ],
        },
        context,
    )
    assert validate_extraction(restored, context)["edges"]


def test_directional_contract_rejects_bill_as_committee_proposer(tmp_path):
    _, source = make_factory(tmp_path)
    body, _ = extraction(source, source["payload"]["units"][0])
    data = json.loads(body["messages"][-1]["content"])
    data["known"] = [
        {"id": "O1", "kind": "organization", "name": "교육위원회"},
        {"id": "B1", "kind": "bill", "name": "의안 2200001"},
        {"id": "B2", "kind": "bill", "name": "의안 2200002"},
    ]
    data["source"] = {
        "U1": "교육위원회가 의안 2200001을 제안했다. 의안 2200002도 검토했다."
    }
    data["types"] = ["committee_proposer"]
    body["messages"][-1]["content"] = json.dumps(data, ensure_ascii=False)

    request = output_contract.directional_extraction_contract(body)
    choices = request["response_format"]["json_schema"]["schema"]["properties"][
        "relations"
    ]["items"]["properties"]["claim"]["enum"]
    kinds = {item["id"]: item["kind"] for item in data["known"]}

    assert "committee_proposer:O1>B1" in choices
    assert all(
        valid_relation_endpoints(role, kinds[left], kinds[right])
        for claim in choices
        for role, pair in [claim.split(":", 1)]
        for left, right in [pair.split(">", 1)]
    )


def test_failed_compact_job_upgrades_to_directional_request(tmp_path):
    factory, _ = make_factory(tmp_path)
    source = factory.store.sources()[0]
    unit = source["payload"]["units"][0]
    body, context = extraction(source, unit)
    context.update(
        sources=[source_dependency(source)],
        artifact_key=source["scope"] + ":" + unit["id"],
        model_signature=SIGNATURE,
        prompt_version=PROMPT_VERSION,
        output_contract=output_contract.COMPACT_CONTRACT,
        retry_attempt=21,
    )
    job_id = factory.store.enqueue(
        "extract",
        fingerprint(["failed-compact"]),
        output_contract.compact_extraction_contract(body),
        context,
    )
    factory.store.update_job(
        job_id, state="failed", error="generated_content_validation_failed"
    )
    failed_at = factory.store.get_job(job_id)["updated_at"]
    assert plan_output_retries(factory.store, SIGNATURE, 256, now=failed_at) == 1
    retry = factory.store.jobs()[-1]
    assert retry["context"]["output_contract"] == (
        "parliament-graph-directional-output-v6"
    )
    assert retry["request"]["response_format"]["json_schema"]["name"] == (
        "parliament_graph_directional_v6"
    )
