"""Bounded global reduction selects old claims without losing their proofs."""

import json
from copy import deepcopy

import pytest
from test_graphrag_engine import SIGNATURE, RemoteFixture, drain, make_factory

from parliament_worker.graphrag import reduction
from parliament_worker.graphrag.claim_selection import (
    CLAIM_SELECTION_CONTRACT,
    SOURCE_GROUP_SELECTION_CONTRACT,
    materialize_selection,
    selection_request,
)
from parliament_worker.graphrag.engine import Factory
from parliament_worker.graphrag.index import source_dependency
from parliament_worker.graphrag.output_retries import plan_output_retries
from parliament_worker.graphrag.prompts import PROMPT_VERSION
from parliament_worker.graphrag.query import _answer_request
from parliament_worker.graphrag.reduction import plan_reductions
from parliament_worker.graphrag.store import GraphStore


def _claim(index: int) -> dict:
    span = ("근거" + str(index)) * 150
    return {
        "text": f"공식 법안 {index}번의 처리 기록",
        "evidence": {
            "documentId": f"doc-{index}",
            "documentVersion": "version-a",
            "extractionVersion": "extract-a",
            "segmentId": f"segment-{index}",
            "sourceUrl": "https://example.org/record",
            "locator": "html:p[1]",
            "start": 0,
            "end": len(span),
            "text": span,
        },
    }


def test_original_bill_policy_claim_stays_out_of_reduction(
    tmp_path, monkeypatch
) -> None:
    """An unsupported current-policy claim cannot become the final answer."""
    store = GraphStore(tmp_path / "state")
    question_id = "question_proposal_gate"
    claim = _claim(0)
    claim["text"] = "양육비 선지급 제도는 국가가 먼저 지급하는 제도임."
    url = "https://example.org/original"
    claim["evidence"]["sourceUrl"] = url
    monkeypatch.setattr(
        store,
        "sources",
        lambda: [
            {
                "payload": {
                    "document": {
                        "sourceKey": "lawmaking-bill-detail",
                        "title": "양육비 선지급 원안",
                        "sourceUrl": url,
                    }
                }
            }
        ],
    )
    body, context = _answer_request("제도는 현재 무엇인가?", [claim["evidence"]])
    job_id = store.enqueue(
        "query_map",
        "proposal-map",
        body,
        {**context, "artifact_key": question_id + ":0", "question_id": question_id},
    )
    store.update_job(job_id, state="submitting")
    store.update_job(
        job_id, state="completed", result={"answer": claim["text"], "claims": [claim]}
    )
    store.put_artifact(
        "question",
        question_id,
        {"sources": []},
        {
            "mode": "global",
            "state": "queued",
            "question": "제도는 현재 무엇인가?",
            "jobs": [job_id],
        },
    )

    assert plan_reductions(store) == 0
    assert store.get_artifact("question", question_id)["payload"]["state"] == (
        "insufficient_evidence"
    )
    assert store.jobs(kind="query_reduce") == []


def test_selection_keeps_original_claim_and_rejects_unknown_ids() -> None:
    """The model only picks IDs; it cannot write the final factual sentence."""
    claims = [_claim(1), _claim(2)]
    body, context = selection_request("무엇이 바뀌었나?", claims)
    payload = json.loads(body["messages"][-1]["content"])
    assert "근거1" not in json.dumps(payload, ensure_ascii=False)
    assert context["output_contract"] == CLAIM_SELECTION_CONTRACT
    result = materialize_selection({"selected": ["C2"], "insufficient": False}, context)
    assert result["claims"] == [claims[1]]
    assert result["reviewRequired"] is True
    with pytest.raises(ValueError):
        materialize_selection({"selected": ["C3"], "insufficient": False}, context)
    with pytest.raises(ValueError):
        materialize_selection({"selected": ["C1"], "insufficient": True}, context)


def test_compound_question_selection_keeps_each_supported_source_host() -> None:
    """A final answer cannot drop the government source after it was mapped."""
    bill, government = _claim(1), _claim(2)
    bill["evidence"]["sourceUrl"] = "https://opinion.lawmaking.go.kr/record"
    government["evidence"]["sourceUrl"] = "https://www.mogef.go.kr/record"
    body, context = selection_request(
        "법안과 정부 후속 발표에서 각각 무엇이 기록됐나?", [bill, government]
    )
    rules = json.loads(body["messages"][-1]["content"])["rules"]
    assert "Never repeat a claim ID in hostChoices or extra" in rules
    candidates = json.loads(body["messages"][-1]["content"])["candidateClaims"]

    assert {item["sourceHost"] for item in candidates} == {
        "opinion.lawmaking.go.kr",
        "www.mogef.go.kr",
    }
    schema = body["response_format"]["json_schema"]
    assert schema["name"] == "parliament_source_group_selection_v2"
    host_schema = schema["schema"]["properties"]["hostChoices"]
    assert set(host_schema["required"]) == {"H1", "H2"}
    assert {tuple(item["enum"]) for item in host_schema["properties"].values()} == {
        ("C1",),
        ("C2",),
    }
    with pytest.raises(ValueError, match="source coverage"):
        materialize_selection({"selected": ["C1"], "insufficient": False}, context)
    result = materialize_selection(
        {"hostChoices": {"H1": "C1", "H2": "C2"}, "extra": []}, context
    )
    assert result["claims"] == [bill, government]


def test_requested_document_facets_keep_followup_release_not_generic_guide() -> None:
    """A shared ministry host cannot substitute a guide for its follow-up release."""
    claims = [_claim(index) for index in range(4)]
    urls = [
        "https://assembly.example/bill/original",
        "https://assembly.example/bill/alternative",
        "https://ministry.example/press/followup",
        "https://ministry.example/guide/program",
    ]
    for claim, url in zip(claims, urls):
        claim["evidence"]["sourceUrl"] = url
    facets = {
        urls[0]: "original_bill",
        urls[1]: "alternative_bill",
        urls[2]: "government_followup",
    }

    body, context = selection_request(
        "원안·대안·정부 후속 발표에서 각각 무엇이 기록됐나?",
        claims,
        source_facets=facets,
    )

    assert body["response_format"]["json_schema"]["name"] == (
        "parliament_source_group_selection_v2"
    )
    assert set(context["requiredFacets"]) == {
        "original_bill",
        "alternative_bill",
        "government_followup",
    }
    choices = {alias: allowed[0] for alias, allowed in context["hostAliases"].items()}
    result = materialize_selection({"hostChoices": choices, "extra": []}, context)
    assert [claim["evidence"]["sourceUrl"] for claim in result["claims"]] == urls[:3]
    followup_alias = next(
        alias for alias, allowed in context["hostAliases"].items() if "C3" in allowed
    )
    with pytest.raises(ValueError, match="source coverage"):
        materialize_selection(
            {"hostChoices": {**choices, followup_alias: "C4"}, "extra": []},
            context,
        )


@pytest.mark.parametrize("kind", ["query_map", "query_reduce"])
@pytest.mark.parametrize("grouped", [False, True])
def test_failed_claim_selection_retries_with_the_same_contract(
    tmp_path, kind: str, grouped: bool
) -> None:
    """A selection failure must not be converted into an answer-writing request."""
    factory, _ = make_factory(tmp_path)
    source = factory.store.sources()[0]
    claims = [_claim(1), _claim(2)]
    if grouped:
        claims[0]["evidence"]["sourceUrl"] = "https://opinion.lawmaking.go.kr/record"
        claims[1]["evidence"]["sourceUrl"] = "https://www.mogef.go.kr/record"
    question = (
        "법안과 정부 발표에서 각각 무엇이 바뀌었나?" if grouped else "법안 처리 변화는?"
    )
    body, context = selection_request(question, claims)
    context.update(
        sources=[source_dependency(source)],
        artifact_key=(
            "question-reduction:reduce:0"
            if kind == "query_map"
            else "question-reduction"
        ),
        question_id="question-reduction",
        model_signature=SIGNATURE,
        prompt_version=PROMPT_VERSION,
    )
    job_id = factory.store.enqueue(kind, "selection-failed", body, context)
    original = deepcopy(factory.store.get_job(job_id))
    if kind == "query_map":
        factory.store.put_artifact(
            "answer_map",
            context["artifact_key"],
            {
                "sources": context["sources"],
                "model_signature": SIGNATURE,
                "prompt_version": PROMPT_VERSION,
            },
            {"claims": [], "answer": "", "insufficient": True},
        )
        factory.store.put_artifact(
            "question",
            context["question_id"],
            {"sources": context["sources"]},
            {
                "mode": "global",
                "state": "queued",
                "question": question,
                "jobs": [job_id],
            },
        )
    factory.store.update_job(
        job_id, state="failed", error="generated_content_validation_failed"
    )

    failed_at = factory.store.get_job(job_id)["updated_at"]
    assert plan_output_retries(factory.store, SIGNATURE, 256, now=failed_at) == 1
    retry = factory.store.jobs()[-1]
    assert retry["context"]["retry_of"] == job_id
    assert retry["context"]["output_contract"] == context["output_contract"]
    assert retry["request"]["response_format"]["json_schema"]["name"] == (
        "parliament_source_group_selection_v2"
        if grouped
        else "parliament_claim_selection_v1"
    )
    payload = json.loads(retry["request"]["messages"][-1]["content"])
    assert payload["task"] == "select grounded claims"
    if grouped:
        assert "Fill each required hostChoices slot" in payload["rules"]
        assert "Never repeat a claim ID in hostChoices or extra" in payload["rules"]
        assert retry["context"]["hostAliases"] == context["hostAliases"]
    else:
        assert "insufficient=true only when selected=[]" in payload["rules"]
    assert factory.store.get_job(job_id)["request"] == original["request"]


def test_reduction_uses_claim_selection_when_full_proofs_cannot_contract(
    tmp_path,
) -> None:
    """Two large proofs can still produce one final model selection request."""
    store = GraphStore(tmp_path / "state")
    question_id = "question_large_proofs"
    claims = [_claim(1), _claim(2)]
    plans = []
    for index, claim in enumerate(claims):
        body, proof_context = _answer_request("법안 처리 변화는?", [claim["evidence"]])
        plans.append(
            {
                "kind": "query_map",
                "key": f"map-{index}",
                "request": body,
                "context": {
                    **proof_context,
                    "artifact_key": f"{question_id}:{index}",
                    "question_id": question_id,
                },
            }
        )
    identifiers = store.enqueue_many(plans)
    for identifier, claim in zip(identifiers, claims):
        store.update_job(identifier, state="submitting")
        store.update_job(
            identifier,
            state="completed",
            result={"answer": claim["text"], "claims": [claim]},
        )
    store.put_artifact(
        "question",
        question_id,
        {"sources": []},
        {
            "mode": "global",
            "state": "queued",
            "question": "법안 처리 변화는?",
            "jobs": identifiers,
        },
    )

    assert plan_reductions(store) == 1
    final = store.jobs(kind="query_reduce")
    assert len(final) == 1
    assert final[0]["context"]["output_contract"] == CLAIM_SELECTION_CONTRACT
    assert len(final[0]["context"]["selectionClaims"]) == 2


def test_poorly_contracting_proof_round_switches_to_selection(
    tmp_path, monkeypatch
) -> None:
    """Many near-singleton proof batches must not consume every round."""
    store = GraphStore(tmp_path / "state")
    question_id = "question_slow_contraction"
    claims = [_claim(index) for index in range(10)]
    for claim in claims:
        claim["evidence"]["text"] = "고정 근거"
        claim["evidence"]["end"] = len("고정 근거")
    facets = ["original_bill", "alternative_bill", "government_followup"]
    keys = ["lawmaking-bill-detail", "lawmaking-bill-detail", "ministry-press-release"]
    titles = ["법률안", "법률안(대안)", "정부 후속 발표"]
    for index in range(3):
        claims[index]["evidence"]["sourceUrl"] = f"https://source.example/{index}"
    claims[2]["text"] = "정부 발표에 따르면, 공식 법안 2번의 처리 기록이 있다."
    monkeypatch.setattr(
        store,
        "sources",
        lambda: [
            {
                "payload": {
                    "document": {
                        "sourceKey": keys[index],
                        "title": titles[index],
                        "sourceUrl": claims[index]["evidence"]["sourceUrl"],
                    }
                }
            }
            for index in range(3)
        ],
    )
    question = "원안·대안·정부 후속 발표에서 각각 무엇이 기록됐나?"
    plans = []
    for index, claim in enumerate(claims):
        body, context = _answer_request(question, [claim["evidence"]])
        plans.append(
            {
                "kind": "query_map",
                "key": f"slow-map-{index}",
                "request": body,
                "context": {
                    **context,
                    "artifact_key": f"{question_id}:{index}",
                    "question_id": question_id,
                },
            }
        )
    identifiers = store.enqueue_many(plans)
    for identifier, claim in zip(identifiers, claims):
        store.update_job(identifier, state="submitting")
        store.update_job(
            identifier,
            state="completed",
            result={"answer": claim["text"], "claims": [claim]},
        )
    store.put_artifact(
        "question",
        question_id,
        {"sources": []},
        {
            "mode": "global",
            "state": "queued",
            "question": question,
            "jobs": identifiers,
            "reductionRound": 2,
        },
    )
    monkeypatch.setattr(
        reduction,
        "_batches",
        lambda _question, points: [points[:2]] + [[p] for p in points[2:]],
    )

    assert plan_reductions(store) == 1
    final = [
        job for job in store.jobs(kind="query_reduce") if job["state"] == "planned"
    ]
    assert len(final) == 1
    assert final[0]["context"]["output_contract"] == SOURCE_GROUP_SELECTION_CONTRACT
    assert set(final[0]["context"]["requiredFacets"]) == set(facets)


def test_reduction_drops_future_tense_not_supported_by_pinned_proof(tmp_path) -> None:
    """A map's unsupported timing must not become a final answer candidate."""
    store = GraphStore(tmp_path / "state")
    question_id = "question_future_tense"
    supported = _claim(1)
    unsupported = _claim(2)
    unsupported["text"] = "양육비 제도는 시행될 예정이다."
    plans = []
    for index, claim in enumerate((supported, unsupported)):
        body, context = _answer_request("각각 무엇이 기록됐나?", [claim["evidence"]])
        plans.append(
            {
                "kind": "query_map",
                "key": f"timing-map-{index}",
                "request": body,
                "context": {
                    **context,
                    "artifact_key": f"{question_id}:{index}",
                    "question_id": question_id,
                },
            }
        )
    identifiers = store.enqueue_many(plans)
    for identifier, claim in zip(identifiers, (supported, unsupported)):
        store.update_job(identifier, state="submitting")
        store.update_job(
            identifier,
            state="completed",
            result={"answer": claim["text"], "claims": [claim]},
        )
    store.put_artifact(
        "question",
        question_id,
        {"sources": []},
        {
            "mode": "global",
            "state": "queued",
            "question": "각각 무엇이 기록됐나?",
            "jobs": identifiers,
        },
    )

    assert plan_reductions(store) == 1
    final = store.jobs(kind="query_reduce")[0]
    request_text = final["request"]["messages"][-1]["content"]
    assert supported["text"] in request_text
    assert unsupported["text"] not in request_text


class SelectionRemote(RemoteFixture):
    """Return a strict selected claim ID for each queued selection request."""

    def poll(self, key: str) -> dict:
        """Complete selection jobs without inventing factual answer text."""
        body = self.accepted[key]
        payload = json.loads(body["messages"][-1]["content"])
        if payload["task"] != "select grounded claims":
            return super().poll(key)
        chosen = payload["candidateClaims"][0]["id"]
        return {
            "state": "completed",
            "_modelMetadata": self.model,
            "result": {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {"selected": [chosen], "insufficient": False}
                            )
                        },
                    }
                ]
            },
        }


def test_multi_batch_selection_completes_through_factory(tmp_path) -> None:
    """Selection maps and final reduce retain fixed evidence across rounds."""
    store = GraphStore(tmp_path / "state")
    question_id = "question_many_large_proofs"
    dependency = {
        "sources": [],
        "model_signature": SIGNATURE,
        "prompt_version": PROMPT_VERSION,
    }
    claims = [_claim(index) for index in range(18)]
    for claim in claims:
        claim["text"] += " 정책 설명" * 38
    plans = []
    for index, claim in enumerate(claims):
        body, proof_context = _answer_request("법안 처리 변화는?", [claim["evidence"]])
        plans.append(
            {
                "kind": "query_map",
                "key": f"original-{index}",
                "request": body,
                "context": {
                    **proof_context,
                    **dependency,
                    "artifact_key": f"{question_id}:{index}",
                    "question_id": question_id,
                },
            }
        )
    identifiers = store.enqueue_many(plans)
    for identifier, claim in zip(identifiers, claims):
        store.update_job(identifier, state="submitting")
        store.update_job(
            identifier,
            state="completed",
            result={"answer": claim["text"], "claims": [claim]},
        )
    store.put_artifact(
        "question",
        question_id,
        dependency,
        {
            "mode": "global",
            "state": "queued",
            "question": "법안 처리 변화는?",
            "jobs": identifiers,
        },
    )
    planned = plan_reductions(store)
    assert planned > 1
    assert all(
        ":reduce:1:" in job["context"]["artifact_key"]
        for job in store.jobs(kind="query_map")
        if job["state"] == "planned"
    )
    assert all(
        job["context"]["output_contract"] == CLAIM_SELECTION_CONTRACT
        for job in store.jobs(kind="query_map")
        if job["state"] == "planned"
    )

    factory = Factory(store, SelectionRemote(), SIGNATURE, poll_seconds=0.1)
    drain(factory, cycles=30)

    answer = store.get_artifact("answer", question_id)
    assert answer is not None, {
        "question": store.get_artifact("question", question_id)["payload"],
        "jobs": [(job["kind"], job["state"], job["error"]) for job in store.jobs()],
    }
    assert 1 <= len(answer["payload"]["claims"]) <= 4
    assert answer["payload"]["private"] is True
    assert all(
        claim["evidence"] in [original["evidence"] for original in claims]
        for claim in answer["payload"]["claims"]
    )
