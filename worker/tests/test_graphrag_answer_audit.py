"""Private question audits separate exact provenance from editorial quality."""

from parliament_worker.graphrag.answer_audit import (
    _answer_coverage_findings,
    audit_question,
)
from parliament_worker.graphrag.answer_quality import editorial_reasons
from parliament_worker.graphrag.store import GraphStore


def _unit() -> dict:
    return {
        "id": "unit-1",
        "documentId": "doc-1",
        "documentVersion": "version-1",
        "extractionVersion": "extract-1",
        "segmentId": "segment-1",
        "sourceUrl": "https://example.org/official",
        "locator": "html:p[1]",
        "licenseStatus": "unknown",
        "start": 10,
        "end": 26,
        "text": "※시행: 2025. 7. 1.",
    }


def _question_with_claim(
    tmp_path, claim_text: str, *, valid_proof: bool = True, mode: str = "global"
):
    store = GraphStore(tmp_path / "state")
    question_id = "question_audit_fixture"
    unit = _unit()
    proof = {
        **unit,
        "text": unit["text"] if valid_proof else "없는 근거",
        "unitId": unit["id"],
    }
    claim = {"text": claim_text, "evidence": proof}
    job_id = store.enqueue(
        "query_map" if mode == "global" else "query_local",
        "map-1",
        {"messages": []},
        {
            "question_id": question_id,
            "artifact_key": question_id + ":0" if mode == "global" else question_id,
            "units": {"S1": unit},
        },
    )
    store.update_job(job_id, state="submitting")
    store.update_job(
        job_id,
        state="completed",
        result={
            "answer": claim_text,
            "claims": [claim],
            "insufficient": False,
            "private": True,
            "reviewRequired": True,
        },
    )
    store.put_artifact(
        "question",
        question_id,
        {"sources": []},
        {
            "mode": mode,
            "state": "queued",
            "question": "언제 시행했나?",
            "jobs": [job_id],
        },
    )
    return store, question_id, claim


def test_audit_flags_unproven_future_and_inline_evidence(tmp_path) -> None:
    """A matching source quote does not clear a misleading answer sentence."""
    store, question_id, claim = _question_with_claim(
        tmp_path,
        "2025. 7. 1. 시행될 예정입니다. (근거: '※시행: 2025. 7. 1.')",
    )
    report = audit_question(store, question_id)
    assert report["mapJobs"] == {"completed": 1, "total": 1, "failed": 0}
    assert report["claimsChecked"] == 1
    assert report["structuralFindings"] == []
    assert {item["reason"] for item in report["editorialFindings"]} == {
        "inline_evidence_in_claim",
        "unproven_future_tense",
    }
    assert report["uniqueEditorialClaims"] == 1
    assert all(claim["text"] not in str(item) for item in report["editorialFindings"])
    assert report["publicationApproved"] is False


def test_unproven_source_absence_is_excluded_from_reduction() -> None:
    """An unrelated excerpt cannot prove that the requested record is absent."""
    unsupported = {
        "text": "양육비 선지급제 관련 정부 후속 발표 기록 없음",
        "evidence": {"text": "경상남도의회"},
    }
    supported = {
        "text": "자료에는 관련 기록이 없다고 명시되어 있다.",
        "evidence": {"text": "관련 기록 없음"},
    }

    assert "unproven_source_absence" in editorial_reasons(unsupported)
    assert "unproven_source_absence" not in editorial_reasons(supported)
    assert "unproven_source_absence" in editorial_reasons(
        {
            "text": "양육비 선지급제 내용은 제공된 자료에 기록되어 있지 않음",
            "evidence": {"text": "전라남도의회"},
        }
    )


def test_name_and_locality_alone_do_not_prove_an_office_claim() -> None:
    """A person directory row without a role cannot justify office wording."""
    unsupported = {
        "text": "정명근은 경기도 화성시의 직책을 보유함",
        "evidence": {"text": "경기도 화성시 정명근"},
    }
    supported = {
        "text": "정명근은 경기도 화성시 시장 직책을 맡았다.",
        "evidence": {"text": "경기도 화성시장 정명근"},
    }

    assert "unproven_office_claim" in editorial_reasons(unsupported)
    assert "unproven_office_claim" not in editorial_reasons(supported)


def test_name_and_locality_alone_do_not_prove_residence() -> None:
    """A locality in a member row is not evidence of a home address."""
    unsupported = {
        "text": "정명근은 경기도 화성시에 거주한다.",
        "evidence": {"text": "경기도 화성시 정명근"},
    }
    supported = {
        "text": "정명근은 경기도 화성시에 거주한다.",
        "evidence": {"text": "정명근의 거주지는 경기도 화성시"},
    }

    assert "unproven_residence_claim" in editorial_reasons(unsupported)
    assert "unproven_residence_claim" not in editorial_reasons(supported)


def test_original_bill_proposal_is_not_presented_as_current_policy() -> None:
    current_sounding = {
        "text": "양육비 선지급 제도는 국가가 먼저 지급한 후 채무자로부터 회수하는 제도임.",
        "evidence": {"text": "이에 양육비 선지급제도를 신설하려는 것임."},
    }
    attributed = {
        **current_sounding,
        "text": "원안은 양육비 선지급제도를 신설하려고 제안했다.",
    }

    assert "proposal_as_current_fact" in editorial_reasons(
        current_sounding, "original_bill"
    )
    assert "proposal_as_current_fact" not in editorial_reasons(
        attributed, "original_bill"
    )
    assert "proposal_as_current_fact" not in editorial_reasons(current_sounding)


def test_original_bill_policy_name_does_not_evade_current_fact_gate() -> None:
    """A policy name ending in 제 must not turn a proposal into current fact."""
    claim = {
        "text": (
            "양육비 선지급제는 국가 또는 양육비이행관리원이 양육비 채권자에게 "
            "양육비를 대신 지급한 후 양육비 채무자로부터 회수하는 제도임."
        ),
        "evidence": {"text": "양육비 선지급제도를 신설하려는 원안임."},
    }

    assert "proposal_as_current_fact" in editorial_reasons(claim, "original_bill")
    assert "proposal_as_current_fact" not in editorial_reasons(claim)


def test_original_bill_action_requires_proposal_attribution() -> None:
    """A proposed amendment must not read like a completed policy change."""
    claim = {
        "text": "양육비 선지급제도를 신설하고 신청인의 자격요건 조사 근거를 마련함",
        "evidence": {
            "text": "다. 양육비 선지급제도를 신설하고 조사 근거를 마련함(안 제21조의6)."
        },
    }
    attributed = {
        **claim,
        "text": "원안은 양육비 선지급제도 신설과 조사 근거를 제안했다.",
    }

    assert "proposal_as_current_fact" in editorial_reasons(claim, "original_bill")
    assert "proposal_as_current_fact" not in editorial_reasons(
        attributed, "original_bill"
    )


def test_government_action_requires_announcement_attribution() -> None:
    """A ministry statement alone does not independently verify its action."""
    claim = {
        "text": "양육비 선지급금 회수 절차를 본격적으로 운영하고 있다.",
        "evidence": {"text": "회수 절차를 본격적으로 운영하고 있다."},
    }
    attributed = {
        **claim,
        "text": "여성가족부는 회수 절차를 본격적으로 운영하고 있다고 밝혔다.",
    }

    assert "announcement_as_verified_action" in editorial_reasons(
        claim, "government_followup"
    )
    assert "announcement_as_verified_action" not in editorial_reasons(
        attributed, "government_followup"
    )


def test_government_followup_keeps_announcement_boundary_for_other_verbs() -> None:
    """A different action verb must not bypass the announcement boundary."""
    claim = {
        "text": "금융결제원 등과 연계한 선지급 회수시스템을 구축하였다.",
        "evidence": {"text": "선지급 회수시스템을 구축하였다."},
    }

    assert "announcement_as_verified_action" in editorial_reasons(
        claim, "government_followup"
    )


def test_suspect_child_support_payment_recipient_requires_review() -> None:
    claim = {
        "text": "양육비 선지급금은 양육비 채무자에게 먼저 지급한다.",
        "evidence": {"text": "양육비 채무자에게 먼저 지급"},
    }

    assert "payment_recipient_review" in editorial_reasons(claim, "original_bill")


def test_original_bill_facet_excludes_unattributed_policy_claim(tmp_path) -> None:
    """An original proposal does not establish the policy's current state."""
    store, question_id, _ = _question_with_claim(
        tmp_path, "양육비 선지급 제도는 국가가 먼저 지급하는 제도임."
    )
    url = "https://example.org/official"
    store.put_source(
        url,
        url,
        {
            "document": {
                "sourceKey": "lawmaking-bill-detail",
                "title": "양육비 선지급 원안",
                "sourceUrl": url,
            }
        },
    )

    report = audit_question(store, question_id)
    assert {item["reason"] for item in report["editorialFindings"]} == {
        "proposal_as_current_fact"
    }
    assert report["sourceFacets"]["original_bill"]["mappedClaims"] == 0


def test_audit_reports_incorrect_persisted_proof_and_partial_work(tmp_path) -> None:
    """A completed result with a broken quote cannot pass structural review."""
    store, question_id, _ = _question_with_claim(
        tmp_path, "제도가 시행됐다.", valid_proof=False
    )
    report = audit_question(store, question_id)
    assert report["questionState"] == "queued"
    assert [item["reason"] for item in report["structuralFindings"]] == [
        "evidence_span_mismatch"
    ]
    assert report["publicationApproved"] is False


def test_audit_checks_the_persisted_final_answer(tmp_path) -> None:
    """A completed answer remains private and its final proof is rechecked."""
    store, question_id, claim = _question_with_claim(tmp_path, "제도가 시행됐다.")
    store.put_artifact(
        "answer",
        question_id,
        {"sources": []},
        {
            "answer": claim["text"],
            "claims": [claim],
            "insufficient": False,
            "private": True,
            "reviewRequired": True,
        },
    )
    report = audit_question(store, question_id)
    assert report["questionState"] == "completed"
    assert report["allMapsComplete"] is True
    assert report["claimsChecked"] == 2
    assert report["uniqueClaimsChecked"] == 1
    assert report["structuralFindings"] == []
    assert report["publicationApproved"] is False


def test_abstained_final_answer_reports_insufficient_evidence(tmp_path) -> None:
    """A completed model job must not imply the question was answered."""
    from parliament_worker.graphrag.query import _snapshot, question_status

    store, question_id, _ = _question_with_claim(tmp_path, "과거 직위만 확인됨")
    store.put_artifact(
        "question",
        question_id,
        {"sources": []},
        {
            "question": "현재 재임 여부는?",
            "mode": "local",
            "snapshot": _snapshot(store),
        },
    )
    store.put_artifact(
        "answer",
        question_id,
        {"sources": []},
        {
            "answer": "",
            "claims": [],
            "insufficient": True,
            "private": True,
            "reviewRequired": True,
            "answerCoverageFindings": ["current_tenure_unanswered"],
        },
    )

    status = question_status(store, question_id)

    assert status["state"] == "insufficient_evidence"
    assert status["claims"] == []
    assert status["answerCoverageFindings"] == ["current_tenure_unanswered"]


def test_local_answer_audit_has_no_map_completion_claim(tmp_path) -> None:
    """A scoped person answer is audited without implying global map coverage."""
    store, question_id, _ = _question_with_claim(
        tmp_path, "의원이 법안을 제안했다.", mode="local"
    )
    report = audit_question(store, question_id)
    assert report["claimsChecked"] == 1
    assert report["allMapsComplete"] is None
    assert report["structuralFindings"] == []


def test_audit_detects_unanswered_current_tenure_question(tmp_path) -> None:
    """A dated appointment alone must not pass a two-part currentness question."""
    store, question_id, claim = _question_with_claim(
        tmp_path,
        "2024년 12월 국가인권위원회 사무총장에 이석준이 임명되었다.",
        mode="local",
    )
    prior = store.get_artifact("question", question_id)
    store.put_artifact(
        "question",
        question_id,
        prior["dependency"],
        {
            **prior["payload"],
            "question": (
                "2024년 임명 발표의 직위는 무엇이고, "
                "2026년 현재 재임 여부도 확인되나?"
            ),
        },
    )
    store.put_artifact(
        "answer",
        question_id,
        {"sources": []},
        {
            "answer": claim["text"],
            "claims": [claim],
            "insufficient": False,
            "private": True,
            "reviewRequired": True,
        },
    )

    report = audit_question(store, question_id)
    assert report["structuralFindings"] == []
    assert report["answerCoverageFindings"] == ["current_tenure_unanswered"]


def test_currentness_audit_catches_role_between_current_and_tenure() -> None:
    """A dated former office must not answer a question about the office now."""
    question = {
        "payload": {
            "question": "김인태의 현재 열린민주당 위원장 재임 여부와 관측 시점은?"
        }
    }
    final = {
        "payload": {
            "answer": "2022-12-23 기준 김인태는 열린민주당 위원장이었습니다.",
            "insufficient": False,
        }
    }

    assert _answer_coverage_findings(question, final) == ["current_tenure_unanswered"]


def test_currentness_audit_requires_observation_time_not_tenure_start() -> None:
    """A role start year and present tense do not date the source observation."""
    question = {
        "payload": {"question": "이순미의 현재 상임위원 재임 여부와 관측 시점은?"}
    }
    final = {
        "payload": {
            "answer": "이순미는 2025년부터 현재까지 상임위원으로 재임 중이다.",
            "insufficient": False,
        }
    }

    assert _answer_coverage_findings(question, final) == [
        "observation_time_unanswered",
        "current_tenure_unverified",
    ]


def test_audit_flags_english_inline_quote(tmp_path) -> None:
    """Local wiki answers may leak a model's English proof label into prose."""
    store, question_id, _ = _question_with_claim(
        tmp_path, "제도가 시행됐다. (quote: '※시행: 2025. 7. 1.')", mode="local"
    )
    report = audit_question(store, question_id)
    assert [item["reason"] for item in report["editorialFindings"]] == [
        "inline_evidence_in_claim"
    ]


def test_audit_flags_korean_inline_quote(tmp_path) -> None:
    """A generated Korean proof label belongs in evidence, not answer prose."""
    store, question_id, _ = _question_with_claim(
        tmp_path, "제도가 시행됐다. (인용: '※시행: 2025. 7. 1.')", mode="local"
    )
    report = audit_question(store, question_id)
    assert [item["reason"] for item in report["editorialFindings"]] == [
        "inline_evidence_in_claim"
    ]


def test_global_audit_separates_mapped_and_final_source_facets(tmp_path) -> None:
    """A mapped bill proof does not imply the final answer covers every facet."""
    store, question_id, claim = _question_with_claim(tmp_path, "제도가 시행됐다.")
    for kind, title, url in (
        ("lawmaking-bill-detail", "원안", "https://example.org/official"),
        ("lawmaking-bill-detail", "위원회 대안", "https://example.org/alt"),
        ("ministry-press-release", "정부 후속", "https://example.org/gov"),
    ):
        store.put_source(
            url,
            url,
            {"document": {"sourceKey": kind, "title": title, "sourceUrl": url}},
        )

    mapped = audit_question(store, question_id)["sourceFacets"]
    assert mapped == {
        "original_bill": {"mappedClaims": 1, "finalClaims": 0},
        "alternative_bill": {"mappedClaims": 0, "finalClaims": 0},
        "government_followup": {"mappedClaims": 0, "finalClaims": 0},
    }

    store.put_artifact(
        "answer",
        question_id,
        {"sources": []},
        {
            "answer": claim["text"],
            "claims": [claim],
            "insufficient": False,
            "private": True,
            "reviewRequired": True,
        },
    )
    final = audit_question(store, question_id)["sourceFacets"]
    assert final["original_bill"]["finalClaims"] == 1
    assert final["alternative_bill"]["finalClaims"] == 0
