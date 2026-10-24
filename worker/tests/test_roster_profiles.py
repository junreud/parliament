"""Profile refresh detects identity changes without reassigning office records."""

from pathlib import Path

import pytest

from parliament_worker.roster.profiles import collect_profiles


def spec():
    return {
        "id": "ministry-current",
        "sourceUrl": "https://www.opm.go.kr/opm/prime/profile.do",
        "expectedName": "김사람",
        "nameSelector": "h1",
        "contextSelector": "article",
        "organizationCode": "org1",
        "organizationName": "기관",
        "position": "장관",
    }


def test_profile_identity_change_is_review_needed_and_keeps_raw(tmp_path: Path):
    report = collect_profiles(
        [spec()],
        lambda url: "<article><h1>박사람</h1><p>장관</p></article>".encode(),
        tmp_path,
        "run1",
    )
    assert report["records"] == []
    assert report["observations"][0]["status"] == "identity_changed"
    assert len(list((tmp_path / "raw").glob("*.bin"))) == 1


def test_profile_and_source_role_remain_unreviewed(tmp_path: Path):
    raw = "<article><h1>김사람</h1><p>장관</p></article>".encode()
    report = collect_profiles([spec()], lambda url: raw, tmp_path, "run1")
    row = report["records"][0]
    assert row["identityStatus"] == "source_local_candidate"
    assert row["excerpt"] == "김사람 장관"
    assert row["position"] == "장관"
    assert row["licenseStatus"] == "unknown"
    assert row["evidenceLocator"] == "html:article"
    again = collect_profiles(
        [spec()], lambda url: (_ for _ in ()).throw(AssertionError()), tmp_path, "run1"
    )
    assert again == report


def test_table_caption_and_selected_row_form_one_bounded_excerpt(tmp_path: Path):
    selected = spec() | {
        "nameSelector": 'td:-soup-contains("김사람")',
        "contextSelector": 'tr:has(td:-soup-contains("김사람"))',
        "tableCaptionSelector": 'table:has(td:-soup-contains("김사람")) > caption',
    }
    raw = (
        "<table><caption>기관 인사</caption>"
        "<tr><td>장관</td><td>김사람</td></tr>"
        "<tr><td>차관</td><td>박사람</td></tr></table>"
    ).encode()
    result = collect_profiles([selected], lambda url: raw, tmp_path, "run1")
    row = result["records"][0]
    assert row["excerpt"] == "기관 인사 장관 김사람"
    assert "박사람" not in row["excerpt"]
    assert row["evidenceLocator"] == (
        'html:table:has(td:-soup-contains("김사람")) > caption'
        ' + tr:has(td:-soup-contains("김사람"))'
    )


def test_table_caption_must_belong_to_selected_row(tmp_path: Path):
    selected = spec() | {
        "nameSelector": 'td:-soup-contains("김사람")',
        "contextSelector": 'tr:has(td:-soup-contains("김사람"))',
        "tableCaptionSelector": "table:first-of-type > caption",
    }
    raw = (
        "<table><caption>다른 기관 인사</caption><tr><td>박사람</td></tr></table>"
        "<table><caption>기관 인사</caption><tr><td>김사람</td></tr></table>"
    ).encode()
    result = collect_profiles([selected], lambda url: raw, tmp_path, "run1")
    assert result["records"] == []
    assert result["observations"][0]["status"] == "markup_changed"


def test_table_caption_cannot_be_mixed_into_json_office_list(tmp_path: Path):
    selected = spec() | {
        "jsonListPath": ["items"],
        "jsonNameField": "name",
        "jsonPositionField": "position",
        "tableCaptionSelector": "table > caption",
    }
    del selected["nameSelector"]
    del selected["contextSelector"]
    with pytest.raises(ValueError, match="invalid bounded JSON office list"):
        collect_profiles([selected], lambda url: b"{}", tmp_path, "run1")


def test_image_alt_does_not_override_profile_body(tmp_path: Path):
    raw = '<article><img alt="전직자"><h1>김사람</h1><p>장관</p></article>'.encode()
    report = collect_profiles([spec()], lambda url: raw, tmp_path, "run1")
    assert report["records"][0]["name"] == "김사람"
    assert "전직자" not in report["records"][0]["excerpt"]


def test_spaced_official_name_preserves_literal_surface_and_context(tmp_path: Path):
    raw = "<article><h1>김 사 람 (金)</h1><p>장관</p></article>".encode()
    result = collect_profiles([spec()], lambda url: raw, tmp_path, "run1")
    assert result["records"][0]["name"] == "김사람"
    assert result["records"][0]["nameSurface"] == "김 사 람"
    assert result["records"][0]["excerpt"] == "김 사 람 (金) 장관"


def test_profile_json_html_field_preserves_full_raw_version(tmp_path: Path):
    import hashlib
    import json

    selected = spec() | {"jsonTextPath": ["vo", "cont"]}
    raw = json.dumps(
        {"vo": {"cont": "<article><h1>김사람</h1><p>장관</p></article>"}},
        ensure_ascii=False,
    ).encode()
    result = collect_profiles([selected], lambda url: raw, tmp_path, "run1")
    row = result["records"][0]
    assert row["rawHash"] == hashlib.sha256(raw).hexdigest()
    assert row["format"] == "json"
    assert row["evidenceLocator"] == "json:/vo/cont|html:article"


def test_json_office_list_uses_only_verified_name_and_role(tmp_path: Path):
    import json

    selected = spec() | {
        "sourceUrl": "https://www.nssc.go.kr/ajaxf/FR_POTAL_SVC/selectPotalEmplList.do",
        "expectedName": "조정아",
        "position": "사무처장",
        "jsonListPath": ["data", "list"],
        "jsonNameField": "USER_NM",
        "jsonPositionField": "JIKGEUP_NM",
    }
    del selected["nameSelector"]
    del selected["contextSelector"]
    raw = json.dumps(
        {
            "data": {
                "list": [
                    {
                        "USER_NM": "다른사람",
                        "JIKGEUP_NM": "위원장",
                        "JIKJANG_TEL": "02-0000-0000",
                    },
                    {
                        "USER_NM": "조정아",
                        "JIKGEUP_NM": "사무처장",
                        "JIKJANG_TEL": "02-1111-1111",
                    },
                ]
            }
        },
        ensure_ascii=False,
    ).encode()

    result = collect_profiles([selected], lambda url: raw, tmp_path, "run1")

    assert result["complete"] is True
    row = result["records"][0]
    assert row["excerpt"] == "조정아 사무처장"
    assert row["evidenceLocator"] == "JSON $.data.list[1] fields USER_NM,JIKGEUP_NM"
    assert row["format"] == "json"
    assert "02-" not in json.dumps(result["records"], ensure_ascii=False)


def test_json_office_list_rejects_contact_field_selection(tmp_path: Path):
    selected = spec() | {
        "jsonListPath": ["data", "list"],
        "jsonNameField": "USER_NM",
        "jsonPositionField": "JIKJANG_TEL",
    }
    del selected["nameSelector"]
    del selected["contextSelector"]

    with pytest.raises(ValueError, match="contact field"):
        collect_profiles([selected], lambda url: b"{}", tmp_path, "run1")


def test_html_and_json_profile_settings_stay_source_local(tmp_path: Path):
    import json

    html_spec = spec()
    json_spec = spec() | {
        "id": "office-json",
        "sourceUrl": "https://www.nssc.go.kr/ajaxf/FR_POTAL_SVC/selectPotalEmplList.do",
        "expectedName": "조정아",
        "position": "사무처장",
        "jsonListPath": ["data", "list"],
        "jsonNameField": "USER_NM",
        "jsonPositionField": "JIKGEUP_NM",
    }
    del json_spec["nameSelector"]
    del json_spec["contextSelector"]
    bodies = {
        html_spec[
            "sourceUrl"
        ]: "<article><h1>김사람</h1><p>장관</p></article>".encode(),
        json_spec["sourceUrl"]: json.dumps(
            {"data": {"list": [{"USER_NM": "조정아", "JIKGEUP_NM": "사무처장"}]}},
            ensure_ascii=False,
        ).encode(),
    }

    result = collect_profiles(
        [html_spec, json_spec], lambda url: bodies[url], tmp_path, "run1"
    )

    assert result["complete"] is True
    assert [row["format"] for row in result["records"]] == ["html", "json"]


def test_dated_office_source_keeps_statement_date_separate_from_collection(
    tmp_path: Path,
):
    selected = spec() | {
        "currentness": "source_dated_acting_statement",
        "sourcePublishedAt": "2026-09-21T00:00:00+09:00",
        "qualificationObservedAt": "2026-09-21T00:00:00+09:00",
        "datePrecision": "date",
    }
    raw = "<article><h1>김사람</h1><p>장관 직무대행</p></article>".encode()
    result = collect_profiles([selected], lambda url: raw, tmp_path, "run1")
    row = result["records"][0]
    assert row["sourcePublishedAt"] == selected["sourcePublishedAt"]
    assert row["qualificationObservedAt"] == selected["qualificationObservedAt"]
    assert row["datePrecision"] == "date"
    assert row["observedAt"] != row["qualificationObservedAt"]
    assert row.get("validFrom") is None


def test_restricted_source_usage_is_preserved_without_approval(tmp_path: Path):
    raw = "<article><h1>김사람</h1><p>장관</p></article>".encode()
    result = collect_profiles(
        [spec() | {"licenseStatus": "restricted"}], lambda url: raw, tmp_path, "run1"
    )
    assert result["records"][0]["licenseStatus"] == "restricted"


def test_embedded_name_needs_review_without_claiming_identity_changed(tmp_path: Path):
    raw = "<article><h1>장관 김사람입니다.</h1></article>".encode()
    result = collect_profiles([spec()], lambda url: raw, tmp_path, "run1")
    assert result["records"] == []
    assert result["observations"][0]["status"] == "name_surface_review_required"


def test_explicit_office_greeting_accepts_attached_copula_name(tmp_path: Path):
    selected = spec() | {"nameTemplate": "기관 장관 {name}입니다."}
    raw = "<article><h1>안녕하십니까. 기관 장관 김사람입니다.</h1></article>".encode()

    result = collect_profiles([selected], lambda url: raw, tmp_path, "run1")

    assert len(result["records"]) == 1
    assert result["records"][0]["nameSurface"] == "김사람"
    assert result["records"][0]["identityStatus"] == "source_local_candidate"


def test_explicit_office_greeting_rejects_stale_name_elsewhere(tmp_path: Path):
    selected = spec() | {"nameTemplate": "기관 장관 {name}입니다."}
    raw = (
        "<article><h1>기관 장관 박사람입니다. 전임 김사람</h1>"
        "<p>김사람 장관 경력</p></article>"
    ).encode()

    result = collect_profiles([selected], lambda url: raw, tmp_path, "run1")

    assert result["records"] == []
    assert result["observations"][0]["status"] == "name_surface_review_required"


def test_explicit_name_template_requires_office_role(tmp_path: Path):
    selected = spec() | {"nameTemplate": "{name}입니다."}

    with pytest.raises(ValueError, match="invalid explicit office name template"):
        collect_profiles([selected], lambda url: b"", tmp_path, "run1")


def test_each_profile_uses_its_own_name_template(tmp_path: Path):
    first = spec() | {"nameTemplate": "기관 장관 {name}입니다."}
    second = spec() | {
        "id": "second-office",
        "sourceUrl": "https://www.mss.go.kr/minister/profile",
        "expectedName": "박사람",
    }
    pages = {
        first[
            "sourceUrl"
        ]: "<article><h1>기관 장관 김사람입니다.</h1></article>".encode(),
        second["sourceUrl"]: "<article><h1>박사람</h1></article>".encode(),
    }

    result = collect_profiles([first, second], lambda url: pages[url], tmp_path, "run1")

    assert [row["name"] for row in result["records"]] == ["김사람", "박사람"]


def test_provisional_organization_namespace_is_preserved(tmp_path: Path):
    raw = "<article><h1>김사람</h1><p>위원장</p></article>".encode()
    selected = spec() | {"organizationNamespace": "KR_ORGANIZATION_LABEL_CANDIDATE"}
    result = collect_profiles([selected], lambda url: raw, tmp_path, "run1")
    assert (
        result["records"][0]["organizationNamespace"]
        == selected["organizationNamespace"]
    )
