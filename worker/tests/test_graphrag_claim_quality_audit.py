"""Private claim risks must stay visible without deciding political truth."""

from copy import deepcopy

from test_graphrag_engine import SIGNATURE, drain, make_factory

from parliament_worker.graphrag.claim_quality_audit import (
    audit_claim_quality,
    claim_quality_flags,
)
from parliament_worker.graphrag.index import current_artifacts
from parliament_worker.graphrag.prompts import GROUP_ID_VERSION
from parliament_worker.graphrag.query import submit_question


def test_scheduled_announcement_is_not_a_completed_event():
    quote = "성평등가족부는 원민경 장관 주재로 간담회를 개최한다."
    claim = "원민경 장관은 간담회를 주재함."

    assert claim_quality_flags(claim, quote) == ["scheduled_source_rendered_completed"]
    assert claim_quality_flags("간담회를 개최할 예정임.", quote) == []


def test_internal_alias_is_flagged_without_changing_quoted_text():
    quote = "의안 2200703 김남희 의원"

    assert claim_quality_flags("김남희 의원이 E1을 발의함.", quote) == [
        "internal_member_alias"
    ]
    assert claim_quality_flags("김남희 의원이 N1을 발의함.", quote) == [
        "internal_member_alias"
    ]


def test_internal_graph_ids_are_flagged_in_claim_text_only():
    identifier = "p_" + "a" * 64
    quote = "김남희 의원이 법안을 발의함."

    assert claim_quality_flags(f"{identifier}가 법안을 발의함.", quote) == [
        "internal_graph_id"
    ]
    assert claim_quality_flags("김남희 의원이 법안을 발의함.", identifier) == []


def test_audit_keeps_pinned_report_and_evidence_reviewable():
    quote = "성평등가족부는 원민경 장관 주재로 간담회를 개최한다."
    source = {
        "scope": "ministry:press:1",
        "fingerprint": "source-1",
        "generation": 1,
        "payload": {"units": []},
    }
    report = {
        "kind": "community",
        "key": "leaf-1",
        "version": "report-1",
        "dependency": {
            "sources": [
                {"scope": source["scope"], "fingerprint": "source-1", "generation": 1}
            ],
            "group_id_version": GROUP_ID_VERSION,
        },
        "payload": {
            "level": 0,
            "public": False,
            "groups": [
                {
                    "id": "group-1",
                    "claims": [
                        {
                            "text": "원민경 장관은 E1 간담회를 주재함.",
                            "evidence": {
                                "id": "evidence-1",
                                "sourceUrl": "https://example.go.kr/press",
                                "text": quote,
                            },
                        }
                    ],
                }
            ],
        },
    }
    snapshot = {
        "sources": [source],
        "model": None,
        "artifacts": {"graph": [], "community": [report]},
    }

    result = audit_claim_quality(snapshot)

    assert result["public"] is False
    assert result["humanReviewed"] is False
    assert result["counts"] == {
        "claims": 1,
        "internal_member_alias": 1,
        "scheduled_source_rendered_completed": 1,
    }
    assert {case["flag"] for case in result["cases"]} == {
        "internal_member_alias",
        "scheduled_source_rendered_completed",
    }
    assert all(case["reportVersion"] == "report-1" for case in result["cases"])
    assert all(case["evidenceQuote"] == quote for case in result["cases"])
    assert all(case["reviewDecision"] == "pending" for case in result["cases"])


def test_global_question_uses_original_source_instead_of_flagged_report(tmp_path):
    """A misleading report must not seed the answer or hide source evidence."""
    factory, _ = make_factory(tmp_path)
    drain(factory)
    report = current_artifacts(factory.store, "community")[0]
    payload = deepcopy(report["payload"])
    claim = payload["groups"][0]["claims"][0]
    claim["text"] = "김가 의원은 E1 간담회를 주재함."
    claim["evidence"]["text"] = "김가 의원 주재로 간담회를 개최한다."
    payload["groups"][0]["summary"] = claim["text"]
    factory.store.put_artifact(
        "community", report["key"], report["dependency"], payload
    )

    question = submit_question(
        factory.store, "간담회는 개최됐나요?", "global", SIGNATURE
    )
    saved = factory.store.get_artifact("question", question["id"])["payload"]

    assert saved["retrieval"]["communityMapTasks"] == 0
    assert saved["retrieval"]["sourceMapTasks"] > 0
    assert saved["retrieval"]["qualityFlaggedCommunityClaimsExcluded"] == 1
