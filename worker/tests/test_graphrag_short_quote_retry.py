"""Length-exhausted community responses retry with bounded source quotes."""

import json
from copy import deepcopy

import pytest
from test_graphrag_engine import SIGNATURE, make_factory

from parliament_worker.graphrag.community_retry import (
    QUOTE_OPTIONS_COMMUNITY_CONTRACT,
    SHORT_QUOTE_COMMUNITY_CONTRACT,
    precise_community_contract,
    quote_options_community_contract,
    short_quote_community_contract,
)
from parliament_worker.graphrag.inputs import fingerprint
from parliament_worker.graphrag.output_retries import plan_output_retries
from parliament_worker.graphrag.prompts import (
    GROUP_ID_VERSION,
    PROMPT_VERSION,
    community_task,
    validate_report,
)


def _community(tmp_path):
    factory, _ = make_factory(tmp_path)
    body, context = community_task(
        [{"id": "person-1", "name": "원민경", "kind": "person"}],
        [{"text": "원민경 장관이 양육비 선지급제 운영 현황을 발표했다."}],
        level=0,
    )
    context["units"]["S1"].update(
        id="official-source-unit-1",
        start=0,
        end=len(context["units"]["S1"]["text"]),
    )
    context.update(
        sources=[],
        children=[],
        group_id_version=GROUP_ID_VERSION,
        artifact_key="length-exhausted-community",
        model_signature=SIGNATURE,
        prompt_version=PROMPT_VERSION,
    )
    return factory, body, context


def test_precise_retry_keeps_name_and_event_tense_rules(tmp_path) -> None:
    """A stricter retry must retain the observed content safeguards."""
    _, body, _ = _community(tmp_path)
    retry = precise_community_contract(body)
    rules = json.loads(retry["messages"][-1]["content"])["rules"]

    assert "E1" in rules
    assert "names" in rules
    assert "scheduled" in rules
    assert "completed" in rules


def test_short_quote_contract_preserves_input_and_exact_proof(tmp_path):
    _, body, context = _community(tmp_path)
    original = deepcopy(body)
    short = short_quote_community_contract(body)
    assert body == original
    claim = short["response_format"]["json_schema"]["schema"]["properties"]["groups"][
        "items"
    ]["properties"]["claims"]["items"]["properties"]
    assert "enum" not in claim["quote"]
    assert claim["quote"]["minLength"] == 2
    assert claim["quote"]["maxLength"] == 120
    rules = json.loads(short["messages"][-1]["content"])["rules"]
    assert "unique exact contiguous 2-120 character quote" in rules
    assert "Copy the FULL supplied source passage" not in rules
    report = {
        "groups": [
            {
                "title": "양육비 선지급제",
                "members": ["E1"],
                "summary": "",
                "claims": [
                    {
                        "text": "운영 현황 발표",
                        "unit": "S1",
                        "quote": "양육비 선지급제 운영 현황",
                    }
                ],
            }
        ]
    }
    assert validate_report(report, context)["groups"][0]["claims"]
    report["groups"][0]["claims"][0]["quote"] = "존재하지 않는 근거"
    with pytest.raises(ValueError, match="quote"):
        validate_report(report, context)


def test_only_length_exhausted_community_uses_short_quote_retry(tmp_path):
    factory, body, context = _community(tmp_path)
    job_id = factory.store.enqueue(
        "community", fingerprint(["length-failed"]), body, context
    )
    factory.store.update_job(
        job_id,
        state="failed",
        error="inference_completion_invalid",
        metadata={"validation_reason": "completion_length_exhausted"},
    )
    original = factory.store.get_job(job_id)
    assert (
        plan_output_retries(factory.store, SIGNATURE, 256, now=original["updated_at"])
        == 1
    )
    retry = factory.store.jobs()[-1]
    assert retry["context"]["output_contract"] == SHORT_QUOTE_COMMUNITY_CONTRACT
    assert retry["context"]["retry_of"] == job_id
    assert retry["idempotency_key"] != original["idempotency_key"]
    assert retry["request"] != original["request"]
    assert factory.store.get_job(job_id)["request"] == body


def test_quote_options_are_exact_bounded_source_spans(tmp_path):
    source = (
        "공식 자료는 양육비 선지급제의 운영 절차와 신청 대상을 설명한다. "
        "담당 기관은 신청 접수 현황을 공개하고 후속 보완 사항을 검토한다. "
        "법안 처리 기록과 실제 시행 기록은 서로 다른 단계로 구분한다."
    )
    body, context = community_task(
        [{"id": "person-1", "name": "원민경", "kind": "person"}],
        [{"text": source}],
        level=0,
    )
    context["units"]["S1"].update(id="source-unit-1", start=0, end=len(source))
    short = short_quote_community_contract(body)
    original = deepcopy(short)
    request = quote_options_community_contract(short)
    assert short == original
    data = json.loads(request["messages"][-1]["content"])
    options = data["quote_options"]["S1"]
    quote = request["response_format"]["json_schema"]["schema"]["properties"]["groups"][
        "items"
    ]["properties"]["claims"]["items"]["properties"]["quote"]
    assert len(options) >= 2
    assert quote["enum"] == options
    assert all(2 <= len(item) <= 88 and source.count(item) == 1 for item in options)
    assert "choose quote verbatim from quote_options" in data["rules"]
    result = {
        "groups": [
            {
                "title": "양육비 선지급제",
                "members": ["E1"],
                "summary": "",
                "claims": [
                    {"text": "공식 자료 설명", "unit": "S1", "quote": options[0]}
                ],
            }
        ]
    }
    assert validate_report(result, context)["groups"][0]["claims"]


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        ("inference_completion_invalid", "completion_length_exhausted"),
        ("generated_content_validation_failed", "graph_quote_absent_or_ambiguous"),
    ],
)
def test_short_quote_failure_retries_with_quote_options(tmp_path, error, reason):
    factory, body, context = _community(tmp_path)
    context.update(output_contract=SHORT_QUOTE_COMMUNITY_CONTRACT, retry_attempt=1)
    failed_request = short_quote_community_contract(body)
    job_id = factory.store.enqueue(
        "community", fingerprint(["short-quote-failed", error]), failed_request, context
    )
    factory.store.update_job(
        job_id,
        state="failed",
        error=error,
        metadata={"validation_reason": reason},
    )
    previous = factory.store.get_job(job_id)
    assert (
        plan_output_retries(factory.store, SIGNATURE, 256, now=previous["updated_at"])
        == 1
    )
    retry = factory.store.jobs()[-1]
    assert retry["context"]["output_contract"] == QUOTE_OPTIONS_COMMUNITY_CONTRACT
    assert retry["context"]["retry_attempt"] == 2
    assert retry["context"]["retry_of"] == job_id
    assert retry["idempotency_key"] != previous["idempotency_key"]
    assert factory.store.get_job(job_id)["request"] == failed_request


def test_quote_options_failure_falls_back_to_assignment(tmp_path):
    factory, body, context = _community(tmp_path)
    context.update(output_contract=QUOTE_OPTIONS_COMMUNITY_CONTRACT, retry_attempt=2)
    options = quote_options_community_contract(short_quote_community_contract(body))
    job_id = factory.store.enqueue(
        "community", fingerprint(["options-failed"]), options, context
    )
    factory.store.update_job(
        job_id,
        state="failed",
        error="inference_completion_invalid",
        metadata={"validation_reason": "completion_length_exhausted"},
    )
    failed_at = factory.store.get_job(job_id)["updated_at"]
    assert plan_output_retries(factory.store, SIGNATURE, 256, now=failed_at) == 1
    retry = factory.store.jobs()[-1]
    assert retry["context"]["output_contract"] == (
        "parliament-community-assignment-output-v5"
    )
    assert retry["request"]["response_format"]["json_schema"]["name"] == (
        "parliament_community_assignment_v5"
    )
    assert "quote_options" not in json.loads(
        retry["request"]["messages"][-1]["content"]
    )


@pytest.mark.parametrize(
    "reason",
    ["unknown_or_duplicate_community_member", "community_membership_incomplete"],
)
def test_repeated_member_error_uses_assignment_without_another_prose_attempt(
    tmp_path, reason: str
) -> None:
    """Repeated membership failures should switch to a bounded assignment."""
    factory, body, context = _community(tmp_path)
    context.update(
        output_contract="parliament-community-precise-output-v4",
        retry_attempt=4,
    )
    request = precise_community_contract(body)
    job_id = factory.store.enqueue(
        "community", fingerprint(["member-error-v4"]), request, context
    )
    factory.store.update_job(
        job_id,
        state="failed",
        error="generated_content_validation_failed",
        metadata={"validation_reason": reason},
    )
    failed_at = factory.store.get_job(job_id)["updated_at"]

    assert plan_output_retries(factory.store, SIGNATURE, 256, now=failed_at) == 1
    retry = factory.store.jobs()[-1]
    assert retry["context"]["retry_attempt"] == 5
    assert retry["context"]["output_contract"] == (
        "parliament-community-assignment-output-v5"
    )
    assert retry["request"]["response_format"]["json_schema"]["name"] == (
        "parliament_community_assignment_v5"
    )
