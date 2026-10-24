"""Versioned output contracts improve shape without weakening evidence checks."""

import json
from copy import deepcopy

import pytest
from test_graphrag_engine import SIGNATURE, RemoteFixture, make_factory

from parliament_worker.graphrag.engine import Factory
from parliament_worker.graphrag.index import source_dependency
from parliament_worker.graphrag.inputs import canonical, fingerprint
from parliament_worker.graphrag.output_contract import ANSWER_CONTRACT
from parliament_worker.graphrag.output_retries import plan_output_retries
from parliament_worker.graphrag.prompts import (
    PROMPT_VERSION,
    SYSTEM,
    community_task,
    extraction,
    request,
    validate_extraction,
)


def legacy_failure(factory, source, *, error="generated_content_validation_failed"):
    """Keep the exact legacy body/key to verify migration does not overwrite it."""
    source = factory.store.sources()[0]
    unit = source["payload"]["units"][0]
    body, context = extraction(source, unit)
    body["response_format"] = {"type": "json_object"}
    context.pop("output_contract", None)
    context.update(
        sources=[source_dependency(source)],
        artifact_key=source["scope"] + ":" + unit["id"],
        model_signature=SIGNATURE,
        prompt_version=PROMPT_VERSION,
    )
    key = fingerprint(
        [source_dependency(source), unit["id"], SIGNATURE, PROMPT_VERSION]
    )
    job = factory.store.enqueue("extract", key, body, context)
    factory.store.update_job(job, state="failed", error=error)
    return factory.store.get_job(job)


def test_extraction_requires_direct_proof_fields_and_bounded_aliases(tmp_path):
    _, source = make_factory(tmp_path)
    body, context = extraction(source, source["payload"]["units"][0])
    assert body["response_format"]["type"] == "json_schema"
    spec = body["response_format"]["json_schema"]
    assert spec["strict"] is True
    relation = spec["schema"]["properties"]["relations"]["items"]
    assert set(relation["required"]) == {"s", "t", "type", "unit", "quote"}
    assert relation["additionalProperties"] is False
    assert relation["properties"]["unit"]["enum"] == ["U1"]
    assert "unknown" not in relation["properties"]["s"]["enum"]
    assert context["output_contract"]


def test_exact_quote_choices_are_bounded_to_source_passages(tmp_path):
    _, source = make_factory(tmp_path)
    body, _ = extraction(source, source["payload"]["units"][0])
    quote = body["response_format"]["json_schema"]["schema"]["properties"]["relations"][
        "items"
    ]["properties"]["quote"]
    assert quote["enum"] == [source["payload"]["units"][0]["text"]]
    assert quote["maxLength"] == 850
    assert body["max_completion_tokens"] == 768


def test_community_contract_requires_evidenced_claims_and_valid_members():
    body, _ = community_task(
        [{"id": "p", "name": "김가", "kind": "person"}],
        [{"text": "김가 의원의 공식 기록"}],
        level=0,
    )
    assert body["response_format"]["type"] == "json_schema"
    group = body["response_format"]["json_schema"]["schema"]["properties"]["groups"][
        "items"
    ]
    assert set(group["required"]) == {"title", "members", "summary", "claims"}
    assert group["properties"]["members"]["items"]["enum"] == ["E1"]
    claim = group["properties"]["claims"]["items"]
    assert set(claim["required"]) == {"text", "unit", "quote"}


def test_answer_contract_requires_a_source_bound_proof_selector():
    body = request(
        "answer grounded question",
        {
            "question": "김남희 의원의 법안은?",
            "graph_or_reports": [],
            "sources": {"S1": "김남희 의원은 법안을 대표발의했다."},
            "rules": "Answer only within supplied records.",
        },
    )
    spec = body["response_format"]["json_schema"]
    assert spec["strict"] is True
    claim = spec["schema"]["properties"]["claims"]["items"]
    assert set(claim["required"]) == {"text", "proof"}
    assert claim["properties"]["proof"]["enum"] == ["S1"]
    assert set(spec["schema"]["required"]) == {"claims"}
    assert spec["name"] == "parliament_answer_claims_v3"


def test_answer_claims_only_response_derives_empty_state_from_validated_claims():
    from parliament_worker.graphrag.output_contract import materialize_answer

    context = {"units": {"S1": {"text": "정부는 선지급금 회수 절차를 운영한다."}}}
    supported = materialize_answer(
        {"claims": [{"text": "정부는 선지급금 회수 절차를 운영한다.", "proof": "S1"}]},
        context,
    )
    empty = materialize_answer({"claims": []}, context)

    assert supported["insufficient"] is False
    assert supported["claims"][0]["quote"] == context["units"]["S1"]["text"]
    assert empty == {"claims": [], "insufficient": True}


def test_global_map_prompt_accepts_evidence_for_one_explicit_question_part():
    from parliament_worker.graphrag.query import _answer_request

    body, _ = _answer_request(
        "원안·대안·정부 후속 발표에서 각각 무엇이 기록됐나?",
        [{"text": "정부는 선지급금 회수 절차를 운영한다."}],
    )
    rules = json.loads(body["messages"][-1]["content"])["rules"]

    assert "any explicit part" in rules
    assert "Do not require this excerpt to cover the other parts" in rules


def test_answer_prompt_identifies_source_and_preserves_announcement_boundary():
    """The model needs source identity to label proposals and ministry claims."""
    from parliament_worker.graphrag.query import _answer_request

    bill_url = "https://opinion.lawmaking.go.kr/gcom/nsmLmSts/out/2201707/detailRP"
    ministry_url = "https://www.mogef.go.kr/nw/rpd/nw_rpd_s001d.do?bbtSn=711265"
    body, _ = _answer_request(
        "원안과 정부 발표에는 각각 무엇이 기록됐나?",
        [
            {"text": "선지급제도를 신설함(안 제21조의6).", "sourceUrl": bill_url},
            {"text": "회수 절차를 운영하고 있다.", "sourceUrl": ministry_url},
        ],
    )
    data = json.loads(body["messages"][-1]["content"])

    assert data["sourceUrls"] == {"S1": bill_url, "S2": ministry_url}
    assert "bill proposal" in data["rules"]
    assert "ministry announcement" in data["rules"]


def test_answer_prompt_abstains_from_undated_current_office_claims():
    from parliament_worker.graphrag.query import _answer_request

    body, _ = _answer_request(
        "인물의 현재 재임 여부는?",
        [{"text": "상임위원 이순미", "sourceUrl": "https://example.org/official"}],
    )
    rules = json.loads(body["messages"][-1]["content"])["rules"]

    assert "undated roster" in rules
    assert "Return claims=[] for unproven current tenure" in rules
    assert "Do not invent collection dates" in rules


@pytest.mark.parametrize(
    ("question", "claim_text", "proof_text"),
    [
        (
            "황운하의 현재 재임 여부와 관측 시점은?",
            "황운하는 제22대 국회의원으로 재임 중이다.",
            '{"name":"황운하","position":"국회의원"}',
        ),
        (
            "김인태의 현재 위원장 재임 여부와 관측 시점은?",
            "2022-12-23 기준 김인태는 위원장이었습니다.",
            "2022-12-23 | 위원장 김인태",
        ),
    ],
)
def test_unanswered_current_tenure_is_not_a_completed_answer(
    question, claim_text, proof_text
):
    """A source-bound role alone cannot complete a present-tenure question."""
    from parliament_worker.graphrag.answer_requests import _answer_request
    from parliament_worker.graphrag.answer_validation import validate_answer
    from parliament_worker.graphrag.output_contract import materialize_answer

    _, context = _answer_request(
        question, [{"id": "unit-1", "start": 0, "text": proof_text}]
    )
    materialized = materialize_answer(
        {"claims": [{"text": claim_text, "proof": "S1"}]}, context
    )

    result = validate_answer(materialized, context)

    assert result["insufficient"] is True
    assert result["answer"] == ""
    assert result["claims"] == []
    assert result["answerCoverageFindings"]


def test_answer_retry_preserves_claims_only_contract_without_mutating_original():
    from parliament_worker.graphrag.output_contract import answer_selector_contract

    original = request(
        "answer grounded question",
        {
            "question": "법안에서 확인되는 변화는?",
            "graph_or_reports": [],
            "sources": {"S1": "선지급 제도를 도입한다."},
            "rules": "Answer only within supplied records.",
        },
    )
    before = deepcopy(original)
    retry = answer_selector_contract(original)
    repeated = answer_selector_contract(retry)

    assert original == before
    assert retry == repeated
    rules = json.loads(retry["messages"][-1]["content"])["rules"]
    assert "Return claims=[] when no supplied source supports a claim" in rules
    assert set(retry["response_format"]["json_schema"]["schema"]["required"]) == {
        "claims"
    }
    assert retry["response_format"]["json_schema"]["strict"] is True


def test_answer_selector_restores_exact_evidence_and_rejects_unknown_unit():
    from parliament_worker.graphrag.output_contract import materialize_answer

    context = {"units": {"S1": {"text": "김가 의원은 법안을 발의했다."}}}
    output = {
        "claims": [{"text": "김가 의원은 법안을 발의했다.", "proof": "S1"}],
        "insufficient": False,
    }
    restored = materialize_answer(output, context)
    assert restored["claims"][0]["quote"] == context["units"]["S1"]["text"]
    assert restored["claims"][0]["unit"] == "S1"
    output["claims"][0]["proof"] = "S2"
    with pytest.raises(ValueError, match="proof"):
        materialize_answer(output, context)


def test_failed_legacy_answer_retries_with_strict_answer_contract(tmp_path):
    factory, _ = make_factory(tmp_path)
    source = factory.store.sources()[0]
    body = request(
        "answer grounded question",
        {
            "question": "김가 의원은 무엇을 했나?",
            "graph_or_reports": [],
            "sources": {"S1": source["payload"]["units"][0]["text"]},
            "rules": "Answer only within supplied records.",
        },
    )
    body["response_format"] = {"type": "json_object"}
    context = {
        "sources": [source_dependency(source)],
        "artifact_key": "answer-legacy",
        "model_signature": SIGNATURE,
        "prompt_version": PROMPT_VERSION,
    }
    job_id = factory.store.enqueue("query_local", "answer-legacy", body, context)
    factory.store.update_job(
        job_id, state="failed", error="generated_content_validation_failed"
    )
    failed_at = factory.store.get_job(job_id)["updated_at"]
    assert plan_output_retries(factory.store, SIGNATURE, 256, now=failed_at) == 1
    retry = factory.store.jobs()[-1]
    assert retry["context"]["output_contract"] == ANSWER_CONTRACT
    assert retry["request"]["response_format"]["type"] == "json_schema"


def test_new_output_contract_keeps_exact_quote_validation(tmp_path):
    _, source = make_factory(tmp_path)
    _, context = extraction(source, source["payload"]["units"][0])
    aliases = {v["kind"]: k for k, v in context["aliases"].items()}
    with pytest.raises(ValueError, match="absent or ambiguous"):
        validate_extraction(
            {
                "entities": [],
                "relations": [
                    {
                        "s": aliases["person"],
                        "t": aliases["bill"],
                        "type": "lead_sponsor",
                        "unit": "U1",
                        "quote": "원문에 없는 발의 내용",
                    }
                ],
            },
            context,
        )


def upgraded(factory, *, capacity=256):
    return Factory(
        factory.store,
        RemoteFixture(),
        SIGNATURE,
        retry_output_failures=True,
        queue_capacity=capacity,
    )


def test_legacy_failure_upgrades_to_compact_after_first_retry(tmp_path):
    factory, source = make_factory(tmp_path)
    prior = legacy_failure(factory, source)
    retry = upgraded(factory)
    retry.plan()
    created = [j for j in retry.store.jobs() if j["id"] != prior["id"]]
    assert len(created) == 1
    assert created[0]["context"]["retry_of"] == prior["id"]
    assert created[0]["idempotency_key"] != prior["idempotency_key"]
    assert created[0]["request"]["response_format"]["type"] == "json_schema"
    assert retry.store.get_job(prior["id"]) == prior
    retry.store.update_job(created[0]["id"], state="failed", error=prior["error"])
    retry.plan()
    assert len(retry.store.jobs()) == 3
    assert retry.store.jobs()[-1]["context"]["retry_of"] == created[0]["id"]


def test_retry_requires_explicit_option(tmp_path):
    factory, source = make_factory(tmp_path)
    legacy_failure(factory, source)
    factory.plan()
    assert len(factory.store.jobs()) == 1


@pytest.mark.parametrize("state", ["completed", "polling", "deferred", "planned"])
def test_success_and_inflight_work_are_never_replaced(tmp_path, state):
    factory, source = make_factory(tmp_path)
    prior = legacy_failure(factory, source)
    # Replace this isolated fixture's failed job with the target state.
    with factory.store._transaction() as db:
        job = deepcopy(prior)
        job.update(state=state, remote_id="known-id", result={"nodes": [], "edges": []})
        db.execute("UPDATE jobs SET data=? WHERE id=?", (json.dumps(job), job["id"]))
    retry = upgraded(factory)
    retry.plan()
    assert len(retry.store.jobs()) == 1
    assert (
        retry.store.get_job(prior["id"])["idempotency_key"] == prior["idempotency_key"]
    )


@pytest.mark.parametrize(
    "error", ["inference_configuration_rejected", "model_revision_mismatch"]
)
def test_configuration_failures_do_not_create_new_model_requests(tmp_path, error):
    factory, source = make_factory(tmp_path)
    legacy_failure(factory, source, error=error)
    upgraded(factory).plan()
    assert len(factory.store.jobs()) == 1


def test_old_source_failure_is_not_retried(tmp_path):
    factory, source = make_factory(tmp_path)
    prior = legacy_failure(factory, source)
    factory.store.retire_source(source["scope"])
    retry = upgraded(factory)
    retry.plan()
    assert len(retry.store.jobs()) == 1
    assert retry.store.get_job(prior["id"])["context"].get("retry_of") is None


def test_retries_do_not_starve_behind_locally_planned_work(tmp_path):
    factory, source = make_factory(tmp_path)
    legacy_failure(factory, source)
    factory.store.enqueue("extract", "other-key", {"messages": []}, {})
    retry = upgraded(factory, capacity=1)
    retry.plan()
    assert len(retry.store.jobs()) == 3
    assert retry.store.jobs()[-1]["context"]["retry_attempt"] == 1


def test_retries_obey_in_flight_capacity(tmp_path):
    factory, source = make_factory(tmp_path)
    legacy_failure(factory, source)
    in_flight = factory.store.enqueue("extract", "other-key", {"messages": []}, {})
    factory.store.update_job(in_flight, state="submitting")
    retry = upgraded(factory, capacity=1)
    retry.plan()
    assert len(retry.store.jobs()) == 2


def test_added_contract_instructions_are_included_in_context_budget():
    data = {
        "known": [],
        "source": {"U1": "source passage"},
        "types": ["records"],
        "rules": "",
    }
    before = len(SYSTEM.encode()) + len(canonical({"task": "extract", **data}))
    data["rules"] = "x" * (4096 - 768 - 256 - before - 1)
    with pytest.raises(ValueError, match="context"):
        request("extract", data)


def test_leaf_community_keeps_full_korean_proofs_for_provider_token_check():
    members = [
        {"id": "bill-original", "name": "원안", "kind": "bill"},
        {"id": "bill-alternative", "name": "대안", "kind": "bill"},
    ]
    proofs = [
        {"id": f"proof-{index}", "text": "양육비 법안 통합 기록 " * 25}
        for index in range(3)
    ]
    body, context = community_task(members, proofs, level=0)
    supplied = json.loads(body["messages"][-1]["content"])["sources"]

    assert list(supplied.values()) == [proof["text"] for proof in proofs]
    assert [unit["text"] for unit in context["units"].values()] == [
        proof["text"] for proof in proofs
    ]


def test_contract_instructions_request_compact_json_and_exclude_unsupported_aliases(
    tmp_path,
):
    _, source = make_factory(tmp_path)
    source["payload"]["entities"].append(
        {
            "id": "unrelated",
            "name": "원문에없는기관",
            "kind": "organization",
            "identifiers": [],
        }
    )
    body, context = extraction(source, source["payload"]["units"][0])
    assert "single compact JSON line" in body["messages"][0]["content"]
    assert all(value["id"] != "unrelated" for value in context["aliases"].values())
    assert "원문에없는기관" not in body["messages"][-1]["content"]


def test_valid_graph_for_same_unit_is_reused_instead_of_retrying_old_failure(tmp_path):
    factory, source = make_factory(tmp_path)
    prior = legacy_failure(factory, source)
    context = prior["context"]
    dependency = {
        k: context[k] for k in ("sources", "model_signature", "prompt_version")
    }
    factory.store.put_artifact(
        "graph", context["artifact_key"], dependency, {"nodes": [], "edges": []}
    )
    upgraded(factory).plan()
    assert len(factory.store.jobs()) == 1


def test_failed_retry_is_scheduled_again_after_cooldown(tmp_path):
    factory, source = make_factory(tmp_path)
    original = legacy_failure(factory, source)
    newer_context = {
        **original["context"],
        "output_contract": "parliament-graph-output-v2",
        "retry_of": original["id"],
    }
    newer = factory.store.enqueue(
        "extract", "failed-v2", original["request"], newer_context
    )
    factory.store.update_job(newer, state="failed", error=original["error"])
    from parliament_worker.graphrag.output_retries import plan_output_retries

    now = factory.store.get_job(newer)["updated_at"]
    assert plan_output_retries(factory.store, SIGNATURE, 256, now=now) == 1
    assert plan_output_retries(factory.store, SIGNATURE, 256, now=now + 31) == 0
    planned = [j for j in factory.store.jobs() if j["state"] == "planned"]
    assert len(planned) == 1
    assert planned[0]["context"]["retry_of"] == newer
    assert planned[0]["context"]["retry_attempt"] == 2
    assert (
        planned[0]["idempotency_key"] != factory.store.get_job(newer)["idempotency_key"]
    )
    assert planned[0]["request"]["response_format"]["type"] == "json_schema"
    assert planned[0]["request"]["temperature"] == 0.2
    assert isinstance(planned[0]["request"]["seed"], int)
    assert plan_output_retries(factory.store, SIGNATURE, 256, now=now + 120) == 0
    factory.store.update_job(
        planned[0]["id"], state="failed", error="generated_content_validation_failed"
    )
    second_failed_at = factory.store.get_job(planned[0]["id"])["updated_at"]
    assert (
        plan_output_retries(factory.store, SIGNATURE, 256, now=second_failed_at + 61)
        == 1
    )
    assert factory.store.jobs()[-1]["context"]["retry_attempt"] == 3


def test_fresh_structured_output_failure_is_retried(tmp_path):
    factory, source = make_factory(tmp_path)
    prior = legacy_failure(factory, source)
    changed = deepcopy(prior)
    changed["context"]["output_contract"] = "parliament-graph-output-v2"
    with factory.store._transaction() as db:
        db.execute(
            "UPDATE jobs SET data=? WHERE id=?",
            (json.dumps(changed), changed["id"]),
        )
    upgraded(factory).plan()
    assert len(factory.store.jobs()) == 2
    planned = factory.store.jobs()[-1]
    assert planned["context"]["retry_attempt"] == 1
    assert planned["request"]["response_format"]["type"] == "json_schema"


def test_remote_execution_failure_is_retried_but_uncertain_acceptance_is_not(tmp_path):
    factory, source = make_factory(tmp_path)
    prior = legacy_failure(factory, source, error="remote_inference_failed")
    assert upgraded(factory).plan()["output_retries"] == 1
    factory.store.update_job(prior["id"], metadata={"completion_uncertain": True})
    # The existing child stays queued; the uncertain parent is never used again.
    assert upgraded(factory).plan()["output_retries"] == 0
