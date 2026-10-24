"""Keep every requested official source category in the first reduction."""

import json

from parliament_worker.graphrag.claim_selection import SOURCE_GROUP_SELECTION_CONTRACT
from parliament_worker.graphrag.query import _answer_request
from parliament_worker.graphrag.reduction import plan_reductions
from parliament_worker.graphrag.store import GraphStore


def _claim(index: int, url: str, text: str) -> dict:
    quote = f"공식 기록 {index}의 고정 구간"
    return {
        "text": text,
        "evidence": {
            "documentId": f"doc-{index}",
            "documentVersion": "version-a",
            "extractionVersion": "extract-a",
            "segmentId": f"segment-{index}",
            "sourceUrl": url,
            "locator": "html:p[1]",
            "start": 0,
            "end": len(quote),
            "text": quote,
        },
    }


def test_first_reduction_pins_requested_original_alternative_and_followup(
    tmp_path, monkeypatch
) -> None:
    """A full-evidence rewrite must not discard the only safe follow-up claim."""
    store = GraphStore(tmp_path / "state")
    question_id = "question_facets_first_round"
    question = "원안·대안·정부 후속 발표에서 각각 무엇이 기록됐나?"
    urls = [
        "https://assembly.example/original",
        "https://assembly.example/alternative",
        "https://ministry.example/followup",
    ]
    claims = [
        _claim(1, urls[0], "원안은 심사에 회부됐다고 기록됐다."),
        _claim(2, urls[1], "위원회 대안이 본회의에서 의결됐다고 기록됐다."),
        _claim(3, urls[2], "정부는 후속 운영 현황을 발표했다."),
    ]
    source_keys = [
        "lawmaking-bill-detail",
        "lawmaking-bill-detail",
        "ministry-press-release",
    ]
    titles = ["양육비 선지급 원안", "양육비 선지급 대안", "후속 운영 발표"]
    monkeypatch.setattr(
        store,
        "sources",
        lambda: [
            {
                "payload": {
                    "document": {
                        "sourceKey": source_keys[index],
                        "title": titles[index],
                        "sourceUrl": urls[index],
                    }
                }
            }
            for index in range(3)
        ],
    )
    plans = []
    for index, claim in enumerate(claims):
        body, context = _answer_request(question, [claim["evidence"]])
        plans.append(
            {
                "kind": "query_map",
                "key": f"facet-map-{index}",
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
        },
    )

    assert plan_reductions(store) == 1
    job = store.jobs(kind="query_reduce")[0]
    assert job["context"]["output_contract"] == SOURCE_GROUP_SELECTION_CONTRACT
    assert set(job["context"]["requiredFacets"]) == {
        "original_bill",
        "alternative_bill",
        "government_followup",
    }
    request = json.loads(job["request"]["messages"][-1]["content"])
    assert {candidate["text"] for candidate in request["candidateClaims"]} == {
        claim["text"] for claim in claims
    }
