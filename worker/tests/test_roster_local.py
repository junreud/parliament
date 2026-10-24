"""Current local officeholder rosters retain source limits and provisional identities."""

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from parliament_worker.roster.adapters import page_url, parse_clik
from parliament_worker.roster.collection import collect_roster
from parliament_worker.roster.local_adapters import (
    parse_gaok,
    parse_goryeong_statement,
    parse_jejusi,
    parse_namk,
    parse_seogwipo,
)


def namk_page(
    office_id: str = "10",
    holder: str = "종로구 홍길동",
    total: int = 1,
    term: str = "09",
) -> bytes:
    """Build a source-shaped membership card without using private contacts."""
    return (
        '<h2 class="sub-tit rg">전국 <span>('
        + str(total)
        + ')</span></h2><input checked name="gsp_srch_class[]" value="'
        + term
        + "\"><a href=\"javascript:GSC_go_url('gourl','view','mod','"
        + office_id
        + '\');"><div class="mem-con-box"><div>서울<span></span>특별시</div><p>'
        + holder
        + "</p></div></a><p>주소 및 연락처 010-1234-5678</p>"
    ).encode()


def test_namk_member_number_identifies_an_office_record_not_a_person() -> None:
    first = parse_namk(namk_page())
    replaced = parse_namk(namk_page(holder="종로구 김새사람"))
    assert first.total == 1
    record = first.records[0]
    assert record["organizationCode"] == "10"
    assert record["organizationName"] == "서울특별시 종로구"
    assert record["sourceRecordId"] == "10:09:홍길동"
    assert record["sourceRecordId"] != replaced.records[0]["sourceRecordId"]
    assert record["identityStatus"] == "source_local_candidate"
    assert record["position"] == "기초단체장 명부 표기"
    assert "010-" not in str(first.records)


def test_namk_requires_a_single_checked_current_term_and_a_member_id() -> None:
    with pytest.raises(ValueError, match="current term"):
        parse_namk(namk_page().replace(b"checked", b""))
    with pytest.raises(ValueError, match="member identity"):
        parse_namk(namk_page().replace(b"GSC_go_url", b"untrusted"))
    with pytest.raises(ValueError, match="current term"):
        parse_namk(namk_page() + b'<input checked name="gsp_srch_class[]" value="06">')


def test_namk_vacancy_preserves_office_without_inventing_a_person() -> None:
    page = parse_namk(namk_page(holder="종로구 공석"))
    assert page.records == []
    assert page.vacancies == 1
    assert page.exclusions[0]["status"] == "vacant"
    assert page.exclusions[0]["organizationName"] == "서울특별시 종로구"


def test_namk_blank_or_unnamed_acting_head_remains_unknown_not_vacant() -> None:
    for holder in ["제주시 ", "고령군 권한대행"]:
        page = parse_namk(namk_page(holder=holder))
        assert page.records == []
        assert page.vacancies == 0
        assert page.exclusions[0]["status"] == "unknown_officeholder"


def test_namk_pagination_keeps_the_requested_current_term() -> None:
    source = {
        "adapter": "namk",
        "url": "https://namk.or.kr/state/member.php",
        "params": {"gsp_srch_class[]": "09"},
    }
    url = page_url(source, 2)
    assert parse_qs(urlparse(url).query) == {"gsp_srch_class[]": ["09"], "gsp_p": ["2"]}


def test_namk_full_page_accounting_distinguishes_vacancy_and_duplicate_pages(
    tmp_path: Path,
) -> None:
    source = {
        "id": "local-heads",
        "adapter": "namk",
        "pageSize": 1,
        "maxPages": 3,
        "url": "https://namk.or.kr/state/member.php",
    }
    payloads = iter([namk_page(total=2), namk_page("11", "중구 공석", total=2)])
    complete = collect_roster(
        source, lambda url: next(payloads), tmp_path, "run-complete"
    )
    assert complete["complete"]
    assert complete["expectedCount"] == 2
    assert complete["recordCount"] == 1
    assert len(complete["exclusions"]) == 1
    assert complete["publication"] == "pending_operator_review"
    duplicate = collect_roster(
        source, lambda url: namk_page(total=2), tmp_path, "run-duplicate"
    )
    assert not duplicate["complete"]
    assert duplicate["errors"][0]["reason"] == "duplicate_record"


def test_namk_duplicate_vacant_office_does_not_fill_the_reported_total(
    tmp_path: Path,
) -> None:
    source = {
        "id": "local-heads",
        "adapter": "namk",
        "pageSize": 1,
        "maxPages": 3,
        "url": "https://namk.or.kr/state/member.php",
    }
    result = collect_roster(
        source,
        lambda url: namk_page(holder="종로구 공석", total=2),
        tmp_path,
        "vacant-repeat",
    )
    assert not result["complete"]
    assert result["errors"][0]["reason"] == "duplicate_office"


def test_clik_unknown_organizations_are_not_merged_by_their_display_name() -> None:
    import json

    rows = [
        {
            "row": '<ul class="rep"><li><span>의원명</span>동명이인</li>'
            "<li><span>지방의회명</span>이름이 같은 의회</li></ul>"
            '<input name="check_box[]" value="당┼동명이인┼이름이 같은 의회┼┼제1대┼'
            + member_id
            + '┼assemblyinfo┼1">'
        }
        for member_id in ["MEMBER1", "MEMBER2"]
    ]
    raw = (
        "var result = eval(" + json.dumps([{"total": "2", "list": rows}]) + ");"
    ).encode()
    page = parse_clik(raw)
    assert page.records[0]["organizationCode"] != page.records[1]["organizationCode"]
    assert all(
        record["organizationIdentityStatus"] == "unresolved" for record in page.records
    )


def test_gaok_uses_member_body_not_duplicate_association_leadership_or_image_alt() -> (
    None
):
    raw = (
        '<div class="executives"><div class="box"><dl><dt>서울특별시장</dt>'
        '<dd>회장 홍길동</dd></dl></div></div><div class="other">'
        '<div class="box"><img alt="image"><dl><dt>서울특별시장</dt><dd>홍길동</dd></dl></div>'
        '<div class="box"><dl><dt>경기도지사</dt><dd>김사람</dd></dl></div>'
        '<!-- <div class="box"><dl><dt>과거도지사</dt><dd>퇴임인</dd></dl></div> -->'
        '</div><img alt="옛 광역시장 과거인"><p>연락처 010-1234-5678</p>'
    ).encode()
    page = parse_gaok(raw)
    assert page.total == 2
    assert [row["name"] for row in page.records] == ["홍길동", "김사람"]
    assert [row["organizationName"] for row in page.records] == ["서울특별시", "경기도"]
    assert all(
        row["identityStatus"] == "source_local_candidate" for row in page.records
    )
    assert all(
        row["evidenceLocator"].startswith("HTML .other .box[") for row in page.records
    )
    assert "010-" not in str(page.records)
    assert not any("validFrom" in row for row in page.records)


def test_gaok_empty_or_unrecognized_office_is_a_failure_not_an_empty_current_roster() -> (
    None
):
    with pytest.raises(ValueError):
        parse_gaok(b"<div class='other'></div>")
    with pytest.raises(ValueError):
        parse_gaok(
            '<div class="other"><div class="box"><dl><dt>회장</dt><dd>이름</dd></dl></div></div>'.encode()
        )


def test_current_local_profile_greetings_have_explicit_person_and_role() -> None:
    jejusi = parse_jejusi(
        "<h4><span><em>제주시장</em><strong>홍길동</strong>입니다</span></h4>".encode()
    )
    seogwipo = parse_seogwipo(
        '<p class="hello-greeting__name">서귀포시장 김사람입니다.</p>'.encode()
    )
    assert jejusi.records[0]["name"] == "홍길동"
    assert jejusi.records[0]["position"] == "제주시장"
    assert seogwipo.records[0]["name"] == "김사람"
    assert all(
        page.records[0]["currentness"] == "source_current_roster"
        for page in [jejusi, seogwipo]
    )
    with pytest.raises(ValueError):
        parse_jejusi(
            "<h4><span><em>제주시장후보자</em><strong>홍길동</strong></span></h4>".encode()
        )


def test_dated_acting_statement_is_not_a_current_roster_or_inferred_term() -> None:
    raw = '<span class="bV_date">2026-09-21 15:19</span><td class="bV_contents">홍길동 고령군수 권한대행은 말했다.</td>'.encode()
    row = parse_goryeong_statement(raw).records[0]
    assert row["currentness"] == "source_dated_office_statement"
    assert row["position"] == "고령군수 권한대행"
    assert row["sourcePublishedAt"] == "2026-09-21T06:19:00+00:00"
    assert row["qualificationObservedAt"] == row["sourcePublishedAt"]
    assert "validFrom" not in row
    with pytest.raises(ValueError):
        parse_goryeong_statement(raw.replace(b"bV_date", b"missing_date"))
