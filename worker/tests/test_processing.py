"""Idempotent local preservation and strict review-gate tests."""

import json
from dataclasses import replace
from decimal import Decimal

import pytest

from parliament_worker.models import Attachment, SourceDocument
from parliament_worker.processing import build_event, process_documents
from parliament_worker.review import Claim, ReviewLedger, SummaryDraft, validate_draft
from parliament_worker.storage import LocalRawStore


def document(now, raw=b"synthetic original"):
    return SourceDocument(
        "korea",
        "9001",
        "https://www.korea.kr/briefing/pressReleaseView.do?newsId=9001",
        "[합성] 안내",
        "합성 안내가 발표되었다.",
        now,
        now,
        ".view_cont",
        agency="합성부",
        raw=raw,
        license_status="allowed",
    )


def test_event_keeps_announced_stage_null_summary_and_evidence(now):
    doc = document(now)
    event = build_event(doc)
    assert event["type"] == "announcement" and event["stage"] == "announced"
    assert event["summary"] is None and event["occurredAt"] is None
    assert event["publishedAt"] == now.isoformat()
    assert event["evidence"][0]["sourceVersion"] == doc.payload_hash
    assert "합성부" in event["coverage"]


@pytest.mark.parametrize("body_status", ["available", "disclaimer_only", "unavailable"])
def test_public_coverage_names_documents_without_internal_processing_codes(
    now, body_status
):
    attachments = (
        Attachment("https://www.korea.kr/common/a.hwp", "합성.hwp", "unsupported_hwp"),
        Attachment(
            "https://www.korea.kr/common/a.hwpx", "합성.hwpx", "unsupported_hwpx"
        ),
        Attachment("https://www.korea.kr/common/a.pdf", "합성.pdf", "optional_pdf"),
    )
    doc = replace(
        document(now),
        body_status=body_status,
        title_locator=".view_title h1",
        attachments=attachments,
    )
    event = build_event(doc)
    coverage = event["coverage"]
    assert all(label in coverage for label in ("한글(HWP)", "한글(HWPX)", "PDF"))
    assert "첨부 문서 유형" in coverage and "내용 미확인" in coverage
    assert not any(
        detail in coverage
        for detail in ("unsupported_", "optional_pdf", "HTML", "파싱", "메타데이터")
    )
    if body_status != "available":
        assert "제목과 게시 정보만" in coverage
        assert "발표 본문을 확인하지 못했습니다" in coverage
        assert event["evidence"][0]["excerpt"] == doc.title
    assert doc.attachments == attachments
    assert event["summary"] is None


def test_coverage_revision_creates_new_derived_version_without_changing_source(now):
    from parliament_worker.activity import version_activity
    from parliament_worker.parsing import PARSER_VERSION

    doc = replace(
        document(now),
        attachments=(
            Attachment(
                "https://www.korea.kr/common/a.hwp", "합성.hwp", "unsupported_hwp"
            ),
        ),
    )
    revised = build_event(doc)
    previous = version_activity(
        revised | {"coverage": "[합성] 이전 공개 설명. 첨부: unsupported_hwp"},
        PARSER_VERSION,
    )
    assert revised["version"] != previous["version"]
    assert revised["id"] == previous["id"]
    assert revised["evidence"] == previous["evidence"]
    assert revised["evidence"][0]["sourceVersion"] == doc.payload_hash
    assert revised["collectedAt"] == previous["collectedAt"]
    assert build_event(doc) == revised


def test_derived_version_changes_with_parser_or_evidence_but_source_hash_does_not(
    now, monkeypatch
):
    doc = document(now)
    original = build_event(doc)
    assert original["version"].startswith("v_")
    assert build_event(doc) == original
    changed_evidence = build_event(replace(doc, locator=".view_cont p"))
    assert changed_evidence["id"] == original["id"]
    assert changed_evidence["version"] != original["version"]
    assert (
        changed_evidence["evidence"][0]["sourceVersion"]
        == original["evidence"][0]["sourceVersion"]
        == doc.payload_hash
    )
    monkeypatch.setattr(
        "parliament_worker.processing.PARSER_VERSION", "synthetic-parser-next"
    )
    changed_parser = build_event(doc)
    assert changed_parser["version"] != original["version"]
    assert changed_parser["evidence"] == original["evidence"]


def test_parser_reprocessing_preserves_raw_version_count_and_first_observation(
    tmp_path, now, monkeypatch
):
    from datetime import timedelta

    store = LocalRawStore(tmp_path)
    doc = document(now)
    original = process_documents([doc], store=store).events[0]
    monkeypatch.setattr(
        "parliament_worker.processing.PARSER_VERSION", "synthetic-parser-next"
    )
    revised = process_documents(
        [replace(doc, collected_at=now + timedelta(days=1))], store=store
    ).events[0]
    assert original["id"] == revised["id"]
    assert original["version"] != revised["version"]
    assert original["collectedAt"] == revised["collectedAt"]
    assert (
        store.version_count(doc.identity)
        == store.version_number(doc.identity, doc.payload_hash)
        == 1
    )
    assert original["corrected"] is revised["corrected"] is False
    store.close()


def test_equal_titles_different_source_ids_remain_distinct(now):
    a = document(now)
    b = replace(a, record_key="9002", source_url=a.source_url.replace("9001", "9002"))
    assert build_event(a)["id"] != build_event(b)["id"]


def test_raw_versions_are_immutable_and_retry_idempotent(tmp_path, now):
    store = LocalRawStore(tmp_path)
    a = document(now)
    first = store.save(a)
    assert store.save(a) == first
    second = store.save(replace(a, raw=b"corrected synthetic original"))
    assert second != first and first.read_bytes() == a.raw
    result = process_documents([a, a], store=store)
    assert len(result.events) == 1


def test_version_changes_keep_identity_and_raise_correction(now, tmp_path):
    store = LocalRawStore(tmp_path)
    a = document(now)
    process_documents([a], store=store)
    result = process_documents([replace(a, raw=b"changed")], store=store)
    assert result.events[0]["id"] == build_event(a)["id"]
    assert result.events[0]["corrected"] is True
    assert result.events[0]["version"] != build_event(a)["version"]


def test_missing_publication_or_restricted_license_is_queued(now):
    result = process_documents(
        [
            replace(document(now), published_at=None),
            replace(document(now), record_key="9002", license_status="restricted"),
        ]
    )
    assert not result.events
    assert {x["reason"] for x in result.review_queue} == {
        "publication_date_missing",
        "license_restricted",
    }


def test_no_output_has_no_filesystem_side_effect(now, tmp_path):
    result = process_documents([document(now)])
    assert len(result.events) == 1
    assert list(tmp_path.iterdir()) == []


def test_each_claim_requires_exact_version_and_original_excerpt(now):
    doc = document(now)
    evidence = build_event(doc)["evidence"][0]
    valid = SummaryDraft(
        "한 줄 요약",
        [
            Claim(
                "합성 안내", evidence["id"], "합성 안내가 발표되었다.", doc.payload_hash
            )
        ],
    )
    assert validate_draft(valid, doc) == []
    invalid = SummaryDraft(
        "검증 실패", [Claim("발표", evidence["id"], "정부가 실제로 시행했다.", "wrong")]
    )
    errors = validate_draft(invalid, doc)
    assert "excerpt_not_in_source" in errors and "source_version_mismatch" in errors


def test_review_limit_and_monthly_cost_are_persistent(tmp_path, now):
    ledger = ReviewLedger(
        tmp_path / "review.sqlite3", monthly_budget=Decimal("100"), daily_cap=3
    )
    for i in range(3):
        ledger.approve(str(i), now)
    with pytest.raises(ValueError, match="daily"):
        ledger.approve("4", now)
    ledger.record_cost(Decimal("70"), now)
    assert ledger.available(now) == Decimal("30")
    with pytest.raises(ValueError, match="budget"):
        ledger.record_cost(Decimal("31"), now)
    ledger.close()
    reopened = ReviewLedger(
        tmp_path / "review.sqlite3", monthly_budget=Decimal("100"), daily_cap=3
    )
    assert reopened.available(now) == Decimal("30")
    reopened.close()


def test_replayed_raw_version_keeps_first_collection_timestamp(tmp_path, now):
    from datetime import timedelta

    store = LocalRawStore(tmp_path)
    original = document(now)
    first = process_documents([original], store=store).events[0]
    later = process_documents(
        [replace(original, collected_at=now + timedelta(hours=1))], store=store
    ).events[0]
    assert first == later
    store.close()
