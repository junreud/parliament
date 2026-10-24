"""Whole-roster consistency and evidence-preserving candidate boundaries."""

import json

import pytest

from parliament_worker.roster.adapters import parse_assembly, parse_clik, parse_parties
from parliament_worker.roster.batches import candidate_batches
from parliament_worker.roster.collection import collect_roster


def assembly(ids, total=2):
    return json.dumps(
        {
            "resultCnt": total,
            "resultList": [
                {"monaCd": key, "hgNm": "동명이인", "polyNm": "정당", "origNm": "지역"}
                for key in ids
            ],
        }
    ).encode()


def test_names_are_not_identity_keys():
    page = parse_assembly(assembly(["A", "B"]))
    assert page.total == 2
    assert len({row["sourceRecordId"] for row in page.records}) == 2


def test_duplicate_pages_are_incomplete_not_retirement(tmp_path):
    source = {
        "id": "assembly",
        "adapter": "assembly",
        "pageSize": 1,
        "maxPages": 3,
        "url": "https://www.assembly.go.kr/portal/cnts/cntsNaas/findNaasThx01.json",
    }
    result = collect_roster(source, lambda url: assembly(["A"]), tmp_path, "run1")
    assert not result["complete"]
    assert result["errors"]
    assert result["records"][0]["currentness"] == "source_current_roster"
    assert "retired" not in json.dumps(result)


def test_total_change_blocks_complete_snapshot(tmp_path):
    payloads = iter([assembly(["A"], 2), assembly(["B"], 3)])
    source = {
        "id": "assembly",
        "adapter": "assembly",
        "pageSize": 1,
        "maxPages": 3,
        "url": "https://www.assembly.go.kr/portal/cnts/cntsNaas/findNaasThx01.json",
    }
    result = collect_roster(source, lambda url: next(payloads), tmp_path, "run1")
    assert not result["complete"]
    assert any("total_changed" == item["reason"] for item in result["errors"])


def test_clik_embedded_json_is_parsed_without_javascript_execution():
    row = '<li><img src="https://clik.nanet.go.kr/clikr-collection/assemblyinfo/2026/002001/id.JPG"><ul class="rep"><li><span>의원명</span><strong>홍길동</strong></li><li><span>지방의회명</span>서울특별시의회</li></ul><input name="check_box[]" value="당┼홍길동┼서울특별시의회┼┼제12대┼CLIKM123┼assemblyinfo┼1"></li>'
    payload = json.dumps([{"total": "1", "list": [{"row": row}]}])
    page = parse_clik(("var result = eval(" + payload + ");").encode())
    assert page.records[0]["namespace"] == "NANET_CLIK_MEMBER"
    assert page.records[0]["organizationCode"] == "002001"
    with pytest.raises(ValueError):
        parse_clik(b'var result = eval(alert("untrusted"));')


def test_party_vacancy_is_not_person_and_contacts_are_excluded():
    raw = "<table><caption>정당등록현황</caption><tbody><tr><td>정당A</td><td>2020-01-01</td><td>공석</td><td>주소</td><td>010-1234-5678</td></tr><tr><td>정당B</td><td>2021-01-01</td><td>권한대행 김사람</td><td>주소</td><td>010-1234-5678</td></tr></tbody></table>".encode()
    page = parse_parties(raw)
    assert page.total == 2
    assert len(page.records) == 1
    assert page.vacancies == 1
    assert page.records[0]["position"] == "대표 권한대행"
    assert "010-" not in json.dumps(page.records)


def test_batches_are_bounded_pending_and_have_fixed_raw_evidence():
    records = [
        {
            "namespace": "OPEN_ASSEMBLY_MONA_CD",
            "sourceRecordId": str(i),
            "name": "이름",
            "position": "국회의원",
            "organizationCode": "assembly",
            "organizationName": "대한민국 국회",
            "sourceUrl": "https://www.assembly.go.kr/",
            "rawHash": "a" * 64,
            "observedAt": "2026-10-09T00:00:00Z",
            "evidenceLocator": f"JSON $.resultList[{i}]",
            "currentness": "source_current_roster",
        }
        for i in range(105)
    ]
    batches = candidate_batches(records)
    assert len(batches) == 3
    assert all(len(b["entities"]) <= 100 for b in batches)
    assert all(not b["activities"] and not b["contexts"] for b in batches)
    assert all(d["licenseStatus"] == "unknown" for b in batches for d in b["documents"])
    assert all(e["documentVersion"] == "a" * 64 for b in batches for e in b["evidence"])
    assert not any(
        m["decision"] == "approved"
        for b in batches
        for d in b["documents"]
        for s in d["segments"]
        for m in s["mentions"]
    )
    again = candidate_batches(records)
    assert [b["id"] for b in batches] == [b["id"] for b in again]


def test_explicit_identity_map_preserves_existing_public_id():
    record = {
        "namespace": "OPEN_ASSEMBLY_MONA_CD",
        "sourceRecordId": "ABC",
        "name": "이름",
        "position": "국회의원",
        "organizationCode": "assembly",
        "organizationName": "대한민국 국회",
        "sourceUrl": "https://www.assembly.go.kr/",
        "rawHash": "a" * 64,
        "observedAt": "2026-10-09T00:00:00Z",
        "evidenceLocator": "JSON $.resultList[0]",
        "currentness": "source_current_roster",
    }
    batches = candidate_batches(
        [record], {"OPEN_ASSEMBLY_MONA_CD:ABC": "existing_public_id"}
    )
    assert any(e["id"] == "existing_public_id" for e in batches[0]["entities"])


def test_verified_common_identity_merges_claims_without_overwriting_sources():
    record = {
        "namespace": "OPEN_ASSEMBLY_MONA_CD",
        "sourceRecordId": "ABC",
        "name": "이름",
        "position": "국회의원",
        "organizationCode": "assembly",
        "organizationName": "대한민국 국회",
        "sourceUrl": "https://www.assembly.go.kr/",
        "rawHash": "a" * 64,
        "observedAt": "2026-10-09T00:00:00Z",
        "evidenceLocator": "JSON $.resultList[0]",
        "currentness": "source_current_roster",
    }
    other = record | {
        "namespace": "NEC_PARTY_HOLDER_SNAPSHOT",
        "sourceRecordId": "holder1",
        "position": "대표",
        "organizationCode": "party1",
        "organizationName": "정당",
    }
    batch = candidate_batches(
        [record, other],
        {
            "OPEN_ASSEMBLY_MONA_CD:ABC": "existing_public_id",
            "NEC_PARTY_HOLDER_SNAPSHOT:holder1": "existing_public_id",
        },
    )[0]
    person = next(e for e in batch["entities"] if e["id"] == "existing_public_id")
    assert len(person["identifiers"]) == 2
    assert len(person["tenures"]) == 2
    assert len(person["facts"]) == 2


def test_reextraction_location_or_identity_changes_get_new_fixed_evidence():
    record = {
        "namespace": "OPEN_ASSEMBLY_MONA_CD",
        "sourceRecordId": "ABC",
        "name": "김사람",
        "position": "국회의원",
        "organizationCode": "assembly",
        "organizationName": "대한민국 국회",
        "sourceUrl": "https://www.assembly.go.kr/",
        "rawHash": "a" * 64,
        "observedAt": "2026-10-09T00:00:00Z",
        "evidenceLocator": "JSON $.resultList[0]",
        "excerpt": "김사람, 김 사람",
    }
    original = candidate_batches([record])[0]
    relocated = candidate_batches(
        [record | {"evidenceLocator": "JSON $.resultList[1]"}]
    )[0]
    new_surface = candidate_batches([record | {"nameSurface": "김 사람"}])[0]
    new_identity = candidate_batches(
        [record], {"OPEN_ASSEMBLY_MONA_CD:ABC": "verified_id"}
    )[0]
    documents = [
        b["documents"][0] for b in [original, relocated, new_surface, new_identity]
    ]
    assert len({d["version"] for d in documents}) == 1
    assert len({d["id"] for d in documents}) == 1
    assert len({d["extractionVersion"] for d in documents}) == 4
    assert original["documents"][0]["segments"][0]["locator"] == "JSON $.resultList[0]"


def test_unchanged_reobservation_reuses_snapshot_and_keeps_new_observation():
    record = {
        "namespace": "OPEN_ASSEMBLY_MONA_CD",
        "sourceRecordId": "ABC",
        "name": "이름",
        "position": "국회의원",
        "organizationCode": "assembly",
        "organizationName": "국회",
        "sourceUrl": "https://www.assembly.go.kr/",
        "rawHash": "a" * 64,
        "observedAt": "2026-10-09T00:00:00Z",
        "evidenceLocator": "JSON $.resultList[0]",
    }
    first = candidate_batches([record])[0]
    again = candidate_batches([record | {"observedAt": "2026-10-10T00:00:00Z"}])[0]
    assert first["id"] == again["id"]
    assert (
        first["documents"][0]["observationId"] != again["documents"][0]["observationId"]
    )
    for field, value in [
        ("licenseStatus", "restricted"),
        ("sourcePublishedAt", "2026-10-01T00:00:00Z"),
        ("position", "국회의장"),
        ("qualificationObservedAt", "2026-09-21T00:00:00Z"),
    ]:
        changed = candidate_batches([record | {field: value}])[0]
        assert (
            changed["documents"][0]["extractionVersion"]
            != first["documents"][0]["extractionVersion"]
        )
