"""Official office tables add source-local candidates without identity merges."""

import pytest

from parliament_worker.roster.graph_refresh import plan_profile_refresh
from parliament_worker.roster.office_table import collect_office_table

URL = "https://www.president.go.kr/information-disclosure/proactive"
MANIFEST = {
    "sourceUrl": URL,
    "tableSelector": "table#offices",
    "expectedCaption": "대통령비서실 비서관급 인사",
    "organizationCode": "1015000",
    "organizationName": "대통령비서실",
    "currentness": "source_current_roster",
    "licenseStatus": "unknown",
}
LEGACY_ID = "provisional-office-profile:" + "a" * 24


def _html(*rows: tuple[str, str], caption: str = "대통령비서실 비서관급 인사") -> bytes:
    body = "".join(
        f'<tr><th scope="row">{role}</th><td>{name}</td></tr>' for role, name in rows
    )
    return (
        f'<table id="offices"><caption>{caption}</caption>'
        f"<tbody>{body}</tbody></table>"
    ).encode()


def test_collects_fixed_rows_and_reuses_only_same_source_record(tmp_path):
    existing = [
        {
            "scope": "roster_KR_OFFICE_PROFILE_CANDIDATE:" + LEGACY_ID,
            "payload": {
                "document": {
                    "sourceUrl": URL,
                    "recordKey": LEGACY_ID,
                },
                "entities": [
                    {"kind": "person", "name": "가나다"},
                    {"kind": "organization", "name": "대통령비서실"},
                ],
                "units": [{"text": "대통령비서실 비서관급 인사 정책실장 가나다"}],
            },
        }
    ]
    result = collect_office_table(
        MANIFEST,
        lambda _: _html(("정책실장", "가나다"), ("비서관", "라마바")),
        tmp_path,
        "offices-1",
        existing_sources=existing,
    )

    assert result["complete"] is True
    assert len(result["records"]) == 2
    assert result["records"][0]["sourceRecordId"] == LEGACY_ID
    assert (
        result["records"][0]["excerpt"] == "대통령비서실 비서관급 인사 정책실장 가나다"
    )
    assert result["records"][1]["name"] == "라마바"
    assert (
        result["records"][1]["sourceRecordId"] != result["records"][0]["sourceRecordId"]
    )
    assert all(item["status"] == "success" for item in result["observations"])


def test_new_occupant_is_new_candidate_and_old_record_requires_review(tmp_path):
    previous = collect_office_table(
        MANIFEST,
        lambda _: _html(("정책실장", "가나다")),
        tmp_path / "previous",
        "offices-old",
    )
    current = collect_office_table(
        MANIFEST,
        lambda _: _html(("정책실장", "라마바")),
        tmp_path / "current",
        "offices-new",
    )

    plan = plan_profile_refresh(previous, current)

    assert [item["name"] for item in plan["stage"]] == ["라마바"]
    assert plan["removedForReview"] == [
        "KR_OFFICE_PROFILE_CANDIDATE:" + previous["records"][0]["sourceRecordId"]
    ]
    assert plan["identityReview"] == []


def test_empty_intermediate_body_keeps_row_selector_and_stable_id(tmp_path):
    raw = (
        '<table id="offices"><caption>대통령비서실 비서관급 인사</caption>'
        '<tbody><tr><th scope="row">정책실장</th><td>가나다</td></tr></tbody>'
        "<tbody></tbody>"
        '<tbody><tr><th scope="row">비서관</th><td>라마바</td></tr></tbody>'
        "</table>"
    ).encode()
    first = collect_office_table(
        MANIFEST, lambda _: raw, tmp_path / "first", "offices-first"
    )
    second = collect_office_table(
        MANIFEST, lambda _: raw, tmp_path / "second", "offices-second"
    )

    assert [item["name"] for item in first["records"]] == ["가나다", "라마바"]
    assert [item["sourceRecordId"] for item in first["records"]] == [
        item["sourceRecordId"] for item in second["records"]
    ]
    assert "tbody:nth-of-type(3)" in first["records"][1]["evidenceLocator"]
    assert plan_profile_refresh(first, second)["stage"] == []


def test_different_organization_does_not_reuse_existing_id(tmp_path):
    existing = [
        {
            "scope": "roster_KR_OFFICE_PROFILE_CANDIDATE:" + LEGACY_ID,
            "payload": {
                "document": {"sourceUrl": URL, "recordKey": LEGACY_ID},
                "entities": [
                    {"kind": "person", "name": "가나다"},
                    {"kind": "organization", "name": "다른 기관"},
                ],
                "units": [{"text": "대통령비서실 비서관급 인사 정책실장 가나다"}],
            },
        }
    ]

    result = collect_office_table(
        MANIFEST,
        lambda _: _html(("정책실장", "가나다")),
        tmp_path,
        "offices-other-organization",
        existing_sources=existing,
    )

    assert result["records"][0]["sourceRecordId"] != LEGACY_ID


def test_row_without_verified_caption_does_not_reuse_existing_id(tmp_path):
    existing = [
        {
            "scope": "roster_KR_OFFICE_PROFILE_CANDIDATE:" + LEGACY_ID,
            "payload": {
                "document": {"sourceUrl": URL, "recordKey": LEGACY_ID},
                "entities": [
                    {"kind": "person", "name": "가나다"},
                    {"kind": "organization", "name": "대통령비서실"},
                ],
                "units": [{"text": "정책실장 가나다"}],
            },
        }
    ]

    result = collect_office_table(
        MANIFEST,
        lambda _: _html(("정책실장", "가나다")),
        tmp_path,
        "offices-unverified-caption",
        existing_sources=existing,
    )

    assert result["records"][0]["sourceRecordId"] != LEGACY_ID


@pytest.mark.parametrize(
    "raw",
    [
        _html(("정책실장", "가나다"), caption="다른 기관 인사"),
        _html(("정책실장", "가나다"), ("정책실장", "가나다")),
        _html(("정책실장", "010-1234-5678")),
    ],
)
def test_changed_caption_duplicate_or_contact_cannot_be_staged(tmp_path, raw):
    with pytest.raises(ValueError):
        collect_office_table(MANIFEST, lambda _: raw, tmp_path, "offices-invalid")
