"""Synthetic offline coverage of source identifiers, dates and parser drift."""

from datetime import timedelta

import pytest

from parliament_worker.connectors import collect, parse_detail, parse_listing
from parliament_worker.models import SourceDocument
from parliament_worker.president import parse_board, parse_schedule


def test_korea_id_date_and_agency_survive_normalization(fixture, now):
    listings = parse_listing("korea", fixture("korea-list.html"))
    assert listings[0].record_key == "900000001"
    assert (
        listings[0].source_url
        == "https://www.korea.kr/briefing/pressReleaseView.do?newsId=900000001"
    )
    document = parse_detail("korea", listings[0], fixture("korea-detail.html"), now)
    assert document.agency == "합성부"
    assert document.published_at.isoformat() == "2026-10-06T09:00:00+09:00"
    assert document.occurred_at is None
    assert "시범사업" in document.body
    assert document.attachments[0].status == "unsupported_hwp"


def test_republication_notice_is_not_a_release_body(fixture, now):
    from parliament_worker.processing import process_documents

    item = parse_listing("korea", fixture("korea-list.html"))[0]
    raw = fixture("korea-disclaimer-only.html")
    doc = parse_detail("korea", item, raw, now)
    assert doc.body_status == "disclaimer_only"
    assert doc.title_locator == ".view_title h1"
    result = process_documents([doc])
    assert len(result.events) == 1
    event = result.events[0]
    assert event["summary"] is None and event["version"].startswith("v_")
    assert event["evidence"][0]["sourceVersion"] == doc.payload_hash
    assert event["evidence"][0]["excerpt"] == doc.title
    assert event["evidence"][0]["locator"] == ".view_title h1"
    assert (
        "제목" in event["coverage"]
        and "첨부 문서의 본문을 확인하지 못했습니다" in event["coverage"]
    )
    assert result.review_queue[0]["scope"] == "summary"
    assert result.review_queue[0]["reason"] == "source_body_disclaimer_only"


def test_empty_korea_body_retains_metadata_without_guessing_contents(fixture, now):
    from bs4 import BeautifulSoup

    from parliament_worker.processing import process_documents

    item = parse_listing("korea", fixture("korea-list.html"))[0]
    raw = fixture("korea-disclaimer-only.html")
    page = BeautifulSoup(raw, "html.parser")
    page.select_one(".view_cont").clear()
    raw = str(page).encode()
    doc = parse_detail("korea", item, raw, now)
    assert doc.body_status == "unavailable"
    result = process_documents([doc])
    assert len(result.events) == 1 and result.events[0]["summary"] is None
    assert "발표 본문을 확인하지 못했습니다" in result.events[0]["coverage"]


def test_substantive_body_with_republication_notice_is_not_metadata_only(fixture, now):
    from bs4 import BeautifulSoup

    from parliament_worker.processing import process_documents

    page = BeautifulSoup(fixture("korea-disclaimer-only.html"), "html.parser")
    paragraph = page.new_tag("p")
    paragraph.string = "[합성] 본문에 사업 검토 절차와 문의 창구를 설명한다."
    page.select_one(".view_cont").insert(0, paragraph)
    doc = parse_detail(
        "korea",
        parse_listing("korea", fixture("korea-list.html"))[0],
        str(page).encode(),
        now,
    )
    assert doc.body_status == "available"
    result = process_documents([doc])
    assert not result.review_queue
    assert result.events[0]["evidence"][0]["locator"] == ".view_cont"
    assert "사업 검토 절차" in result.events[0]["evidence"][0]["excerpt"]


def test_opm_registration_date_and_department(fixture, now):
    item = parse_listing("opm", fixture("opm-list.html"))[0]
    document = parse_detail("opm", item, fixture("opm-detail.html"), now)
    assert item.record_key == "900001"
    assert document.agency == "합성정책실"
    assert document.published_at.date().isoformat() == "2026-10-06"
    assert document.occurred_at is None


def test_president_raw_ids_and_noncommercial_license(fixture, now):
    item = parse_board("president-briefings", fixture("president-list.json"))[0]
    document = parse_detail(
        "president-briefings", item, fixture("president-detail.html"), now
    )
    assert document.record_key == "Synthetic1"
    assert document.license_status == "restricted"
    assert document.locator == ".lineList_v .view_txt"


def test_schedule_occurrence_is_not_invented_publication(fixture, now):
    docs = parse_schedule(fixture("president-schedule.json"), now)
    assert len(docs) == 1
    assert docs[0].published_at is None
    assert docs[0].occurred_at.isoformat() == "2026-10-06T11:00:00+09:00"
    assert docs[0].record_key == "90001"


def test_parser_drift_is_visible_not_empty_success():
    with pytest.raises(ValueError, match="structure"):
        parse_listing("korea", b"<html>unrelated page</html>")


@pytest.mark.parametrize("raw", [b"[]", b"null", b'{"data":{"list":[null]}}'])
def test_malformed_official_json_returns_visible_structure_error(raw, now):
    with pytest.raises(ValueError, match="structure"):
        parse_board("president-briefings", raw)
    with pytest.raises(ValueError, match="structure"):
        parse_schedule(raw, now)


def test_missing_registration_date_is_not_replaced_by_collection(fixture, now):
    item = parse_listing("opm", fixture("opm-list.html"))[0]
    raw = b'<div class="board-view-title-wrap"><h4>title</h4></div><div class="board-view-txt">body</div>'
    doc = parse_detail("opm", item, raw, now)
    # Official list date may be used as provenance; ingestion time is never used.
    assert doc.published_at.date().isoformat() == "2026-10-06"


def test_ninety_day_filter_happens_before_detail_fetch(fixture, now):
    raw = fixture("korea-list.html").replace(b"2026.10.06", b"2026.01.01")
    calls = []

    def fetch(url, **kwargs):
        calls.append(url)
        return raw

    result = collect("korea", fetch, now, max_pages=1)
    assert not result.documents
    assert len(calls) == 1
    assert result.status == "bounded"


def test_collection_retains_failure_report_on_one_bad_article(fixture, now):
    def fetch(url, **kwargs):
        if "View.do" in url:
            raise TimeoutError("timeout")
        return fixture("korea-list.html")

    result = collect("korea", fetch, now, max_pages=1)
    assert result.errors and result.status == "partial"
    assert result.documents == []


def test_missing_list_publication_date_is_reported_before_window_filter(fixture, now):
    raw = fixture("korea-list.html").replace(b"2026.10.06", b"unknown")
    result = collect("korea", lambda url: raw, now, max_pages=1)
    assert result.status == "partial"
    assert result.errors[0]["reason"] == "publication_date_missing"


def test_president_missing_publication_date_is_reported(fixture, now):
    import json

    raw = json.dumps(
        {"data": {"list": [{"BBS_CD": "SyntheticMissing", "SUBJECT": "[합성]"}]}}
    ).encode()

    def fetch(url, **kwargs):
        return raw if "ajaxf/" in url else fixture("president-list.html")

    result = collect("president-briefings", fetch, now, max_pages=1)
    assert result.status == "partial"
    assert result.errors[0]["reason"] == "publication_date_missing"


def test_schedule_real_registration_metadata_is_distinct_from_occurrence(now):
    import json

    raw = json.dumps(
        {
            "data": {
                "list": [
                    {
                        "SCHEDULE_SEQ": 90003,
                        "SCH_TYPE": "R0201",
                        "SCH_DT": "2026.10.06",
                        "SCH_TIME": "10:00",
                        "REG_DATE": 1791208800000,
                        "SUBJECT": "[합성] 일정",
                    }
                ]
            }
        }
    ).encode()
    document = parse_schedule(raw, now)[0]
    assert document.record_key == "90003"
    assert document.published_at is not None
    assert document.published_at != document.occurred_at


def test_president_actual_ajax_wrapper_and_full_registration_time(now):
    import json

    raw = json.dumps(
        {
            "data": {
                "list": [
                    {
                        "BBS_CD": "Synthetic2",
                        "SUBJECT": "[합성] 발표",
                        "WRITE_DT": "2026-10-06 17:56:00.0",
                        "WRITE_DATE": "2026.10.06",
                    }
                ]
            }
        }
    ).encode()
    assert parse_board("president-briefings", raw)[0].published_at.hour == 17


def test_schedule_preserves_original_response_bytes(fixture, now):
    raw = fixture("president-schedule.json")
    assert parse_schedule(raw, now)[0].raw == raw
