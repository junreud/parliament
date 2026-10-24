"""Incremental private GraphRAG staging from complete roster observations."""

import json
from pathlib import Path

import pytest

from parliament_worker.graphrag.inputs import read_sources
from parliament_worker.roster.batches import candidate_batches
from parliament_worker.roster.graph_refresh import (
    backfill_ungrounded_profiles,
    plan_profile_refresh,
    plan_refresh,
    stage_refresh,
    validate_run_pair,
)


def record(
    identity: str, *, name: str = "김사람", stamp: str = "2026-10-16T00:00:00Z"
) -> dict:
    return {
        "namespace": "OPEN_ASSEMBLY_MONA_CD",
        "sourceRecordId": identity,
        "name": name,
        "position": "국회의원",
        "organizationCode": "assembly",
        "organizationName": "대한민국 국회",
        "sourceUrl": "https://www.assembly.go.kr/",
        "rawHash": "a" * 64,
        "observedAt": stamp,
        "evidenceLocator": "JSON $.resultList[0]",
        "currentness": "source_current_roster",
    }


def test_refresh_stages_new_and_material_changes_only():
    before = [record("A"), record("B")]
    after = [
        record("A") | {"rawHash": "b" * 64, "observedAt": "2026-10-17T00:00:00Z"},
        record("B") | {"position": "국회의장"},
        record("C"),
    ]
    plan = plan_refresh(before, after, complete=True)
    assert [row["sourceRecordId"] for row in plan["stage"]] == ["B", "C"]
    assert plan["unchanged"] == 1
    assert plan["removedForReview"] == []


def test_legacy_html_locator_spelling_does_not_requeue_same_evidence():
    old = record("A") | {"evidenceLocator": "HTML html > body > main"}
    new = record("A") | {"evidenceLocator": "html:html > body > main"}
    assert plan_refresh([old], [new], complete=True)["stage"] == []


def test_refresh_quarantines_reused_identity_and_preserves_removed():
    plan = plan_refresh(
        [record("A"), record("B")], [record("A", name="이사람")], complete=True
    )
    assert plan["stage"] == []
    assert plan["identityReview"] == ["OPEN_ASSEMBLY_MONA_CD:A"]
    assert plan["removedForReview"] == ["OPEN_ASSEMBLY_MONA_CD:B"]


def test_incomplete_refresh_never_stages():
    with pytest.raises(ValueError, match="incomplete"):
        plan_refresh([record("A")], [], complete=False)


def test_run_pair_requires_same_complete_source_set():
    source = {"id": "assembly", "adapter": "assembly"}
    coverage = [{"sourceSpec": source, "complete": True, "recordCount": 1}]
    validate_run_pair([record("A")], coverage, [record("A")], coverage)
    with pytest.raises(ValueError, match="source set"):
        validate_run_pair(
            [record("A")],
            coverage,
            [record("A")],
            [{"sourceSpec": {"id": "other"}, "complete": True, "recordCount": 1}],
        )
    with pytest.raises(ValueError, match="incomplete"):
        validate_run_pair(
            [record("A")],
            coverage,
            [record("A")],
            [{"sourceSpec": source, "complete": False, "recordCount": 1}],
        )


def test_stage_refresh_is_private_and_idempotent(tmp_path: Path):
    graph_input = tmp_path / "graph"
    graph_input.mkdir()
    plan = plan_refresh([], [record("A")], complete=True)
    files = stage_refresh(plan, graph_input)
    assert len(files) == 1
    assert stage_refresh(plan, graph_input) == files
    batch = json.loads(files[0].read_text())
    assert batch["activities"] == []
    assert batch["documents"][0]["licenseStatus"] == "unknown"
    assert batch["documents"][0]["segments"][0]["mentions"][0]["decision"] == "pending"


def test_refresh_preserves_existing_person_id_and_selects_new_snapshot(tmp_path: Path):
    graph_input = tmp_path / "graph"
    graph_input.mkdir()
    old = record("A", stamp="2026-10-15T00:00:00Z")
    initial = candidate_batches(
        [old], {"OPEN_ASSEMBLY_MONA_CD:A": "verified_person_id"}
    )[0]
    (graph_input / (initial["id"] + ".json")).write_text(
        json.dumps(initial, ensure_ascii=False)
    )
    new = record("A", stamp="2026-10-16T00:00:00Z") | {"position": "국회의장"}
    stage_refresh(plan_refresh([old], [new], complete=True), graph_input)
    current = read_sources([graph_input])
    assert len(current) == 1
    assert "verified_person_id" in {
        entity["id"] for entity in current[0]["payload"]["entities"]
    }
    assert "국회의장" in current[0]["payload"]["units"][0]["text"]


def test_refresh_rejects_stale_changed_observation(tmp_path: Path):
    graph_input = tmp_path / "graph"
    graph_input.mkdir()
    old = record("A", stamp="2026-10-16T00:00:00Z")
    initial = candidate_batches([old])[0]
    (graph_input / (initial["id"] + ".json")).write_text(
        json.dumps(initial, ensure_ascii=False)
    )
    new = old | {"position": "국회의장"}
    with pytest.raises(ValueError, match="stale"):
        stage_refresh(plan_refresh([old], [new], complete=True), graph_input)


def test_refresh_rejects_equal_instant_with_different_timezone(tmp_path: Path):
    graph_input = tmp_path / "graph"
    graph_input.mkdir()
    old = record("A", stamp="2026-10-16T00:00:00Z")
    initial = candidate_batches([old])[0]
    (graph_input / (initial["id"] + ".json")).write_text(
        json.dumps(initial, ensure_ascii=False)
    )
    new = old | {
        "position": "국회의장",
        "observedAt": "2026-10-16T09:00:00+09:00",
    }
    with pytest.raises(ValueError, match="stale"):
        stage_refresh(plan_refresh([old], [new], complete=True), graph_input)


def profile_run(specs: list[dict], statuses: list[str], records: list[dict]) -> dict:
    return {
        "sourceSpecs": specs,
        "observations": [
            {"id": spec["id"], "status": status}
            for spec, status in zip(specs, statuses)
        ],
        "records": records,
    }


def profile_record(identity: str, *, name: str = "김사람") -> dict:
    return record(identity, name=name) | {"namespace": "KR_OFFICE_PROFILE_CANDIDATE"}


def test_profile_refresh_stages_independent_successes_and_holds_failures():
    first = {"id": "officeA", "sourceRecordId": "A"}
    second = {"id": "officeB", "sourceRecordId": "B"}
    third = {"id": "officeC", "sourceRecordId": "C"}
    old = profile_run(
        [first, second], ["success", "markup_changed"], [profile_record("A")]
    )
    current = profile_run(
        [first, second, third],
        ["success", "success", "failed"],
        [profile_record("A"), profile_record("B")],
    )
    plan = plan_profile_refresh(old, current)
    assert [row["sourceRecordId"] for row in plan["stage"]] == ["B"]
    assert plan["sourceFailures"] == ["officeC"]
    assert plan["removedForReview"] == []


def test_profile_refresh_quarantines_name_conflict_without_retiring_failure():
    first = {"id": "officeA", "sourceRecordId": "A"}
    second = {"id": "officeB", "sourceRecordId": "B"}
    old = profile_run(
        [first, second],
        ["success", "success"],
        [profile_record("A"), profile_record("B")],
    )
    current = profile_run(
        [first, second],
        ["success", "failed"],
        [profile_record("A", name="이사람")],
    )
    plan = plan_profile_refresh(old, current)
    assert plan["stage"] == []
    assert plan["identityReview"] == ["KR_OFFICE_PROFILE_CANDIDATE:A"]
    assert plan["sourceFailures"] == ["officeB"]
    assert plan["removedForReview"] == []


def test_profile_spec_rename_does_not_bypass_identity_review():
    old = profile_run(
        [{"id": "old-office", "sourceRecordId": "A"}],
        ["success"],
        [profile_record("A")],
    )
    current = profile_run(
        [{"id": "new-office", "sourceRecordId": "A"}],
        ["success"],
        [profile_record("A", name="이사람")],
    )
    plan = plan_profile_refresh(old, current)
    assert plan["stage"] == []
    assert plan["identityReview"] == ["KR_OFFICE_PROFILE_CANDIDATE:A"]
    assert plan["removedForReview"] == []


def test_profile_backfill_uses_exact_source_identity_not_name():
    current = profile_run(
        [{"id": "officeA", "sourceRecordId": "A"}],
        ["success"],
        [profile_record("A")],
    )
    scope = "roster_KR_OFFICE_PROFILE_CANDIDATE:A"
    ungrounded = {
        "scope": scope,
        "payload": {
            "entities": [{"kind": "person", "name": "김사람"}],
            "units": [],
        },
    }
    plan = plan_profile_refresh(current, current)
    backfilled = backfill_ungrounded_profiles(plan, current, [ungrounded])
    assert [row["sourceRecordId"] for row in backfilled["stage"]] == ["A"]
    assert backfilled["backfilledCount"] == 1
    assert (
        backfill_ungrounded_profiles(
            plan,
            current,
            [
                ungrounded
                | {"payload": ungrounded["payload"] | {"units": [{"id": "unit"}]}}
            ],
        )["stage"]
        == []
    )


def test_profile_backfill_quarantines_reused_source_identity():
    current = profile_run(
        [{"id": "officeA", "sourceRecordId": "A"}],
        ["success"],
        [profile_record("A", name="새사람")],
    )
    existing = {
        "scope": "roster_KR_OFFICE_PROFILE_CANDIDATE:A",
        "payload": {"entities": [{"kind": "person", "name": "김사람"}], "units": []},
    }
    plan = backfill_ungrounded_profiles(
        plan_profile_refresh(current, current), current, [existing]
    )
    assert plan["stage"] == []
    assert plan["identityReview"] == ["KR_OFFICE_PROFILE_CANDIDATE:A"]


def test_profile_backfill_does_not_repeat_a_source_without_usable_text():
    current = profile_run(
        [{"id": "officeA", "sourceRecordId": "A"}],
        ["success"],
        [profile_record("A") | {"licenseStatus": "restricted"}],
    )
    existing = {
        "scope": "roster_KR_OFFICE_PROFILE_CANDIDATE:A",
        "payload": {"entities": [{"kind": "person", "name": "김사람"}], "units": []},
    }
    plan = backfill_ungrounded_profiles(
        plan_profile_refresh(current, current), current, [existing]
    )
    assert plan["stage"] == []
    assert plan["unavailableForGraph"] == ["KR_OFFICE_PROFILE_CANDIDATE:A"]
