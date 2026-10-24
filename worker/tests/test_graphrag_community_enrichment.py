"""Grounded community summaries select immutable child claims by ID."""

import json
import time
from copy import deepcopy

import pytest

from parliament_worker.graphrag.community_enrichment import (
    build_selection_request,
    materialize_evidence_selection,
    plan_evidence_enrichments,
)
from parliament_worker.graphrag.engine import Factory
from parliament_worker.graphrag.index import routing_current
from parliament_worker.graphrag.output_retries import plan_output_retries
from parliament_worker.graphrag.prompts import GROUP_ID_VERSION, validate_report
from parliament_worker.graphrag.store import GraphStore


def _proof(text: str) -> dict:
    return {
        "documentId": "document-a",
        "documentVersion": "version-a",
        "extractionVersion": "extract-a",
        "segmentId": "segment-a",
        "sourceUrl": "https://example.go.kr/record",
        "unitId": "unit-a",
        "start": 0,
        "end": len(text),
        "text": text,
    }


def _reports() -> tuple[dict, list[dict]]:
    first = {
        "kind": "community",
        "key": "leaf-a",
        "version": "leaf-a-v1",
        "payload": {
            "level": 0,
            "groups": [
                {
                    "id": "group-a",
                    "title": "입법",
                    "members": ["person-a"],
                    "summary": "법안이 발의됐다.",
                    "claims": [
                        {
                            "text": "법안이 발의됐다.",
                            "evidence": _proof("법안이 발의됐다."),
                        }
                    ],
                }
            ],
        },
    }
    second = {
        "kind": "community",
        "key": "leaf-b",
        "version": "leaf-b-v1",
        "payload": {
            "level": 0,
            "groups": [
                {
                    "id": "group-b",
                    "title": "발표",
                    "members": ["person-b"],
                    "summary": "기관이 발표했다.",
                    "claims": [
                        {
                            "text": "기관이 발표했다.",
                            "evidence": _proof("기관이 발표했다."),
                        }
                    ],
                }
            ],
        },
    }
    parent = {
        "kind": "community",
        "key": "parent:1:sample",
        "version": "parent-v1",
        "dependency": {
            "model_signature": "model@revision",
            "prompt_version": "parliament-graphrag-v3",
            "group_id_version": "report-key-scoped-v1",
            "routing_version": "source-entity-overlap-fixed-hub-cap-v3",
            "children": [
                {"kind": "community", "key": first["key"], "version": first["version"]},
                {
                    "kind": "community",
                    "key": second["key"],
                    "version": second["version"],
                },
            ],
        },
        "payload": {
            "level": 1,
            "public": False,
            "reportStatus": "membership_only",
            "groups": [
                {
                    "id": "parent-group-a",
                    "title": "법안",
                    "members": ["group-a"],
                    "summary": "",
                    "claims": [],
                },
                {
                    "id": "parent-group-b",
                    "title": "발표",
                    "members": ["group-b"],
                    "summary": "",
                    "claims": [],
                },
            ],
        },
    }
    return parent, [first, second]


def test_selection_uses_exact_child_claim_and_evidence():
    parent, children = _reports()

    body, context = build_selection_request(parent, children)
    assert body["response_format"]["type"] == "json_schema"
    assert set(context["candidates"]) == {"C1", "C2"}
    assert context["prior_report_version"] == "parent-v1"

    report = materialize_evidence_selection(
        {"selected": {"G1": ["C1"], "G2": ["C2"]}}, context
    )
    assert report["reportStatus"] == "evidence_selected"
    assert report["public"] is False
    assert (
        report["groups"][0]["claims"] == children[0]["payload"]["groups"][0]["claims"]
    )
    assert (
        report["groups"][1]["claims"] == children[1]["payload"]["groups"][0]["claims"]
    )
    assert report["groups"][0]["summary"] == "법안이 발의됐다."


def test_selection_rejects_claim_from_other_group():
    parent, children = _reports()
    _, context = build_selection_request(parent, children)

    with pytest.raises(ValueError, match="group"):
        materialize_evidence_selection({"selected": {"G1": ["C2"], "G2": []}}, context)


@pytest.mark.parametrize("invalid", [[{"id": "C1"}], ["C1", "C1"], ["C999"]])
def test_selection_rejects_invalid_or_duplicate_claim_ids(invalid):
    parent, children = _reports()
    _, context = build_selection_request(parent, children)

    with pytest.raises(ValueError):
        materialize_evidence_selection({"selected": {"G1": invalid, "G2": []}}, context)


def test_selection_excludes_contact_claims_without_sending_them():
    parent, children = _reports()
    children[0] = deepcopy(children[0])
    children[0]["payload"]["groups"][0]["claims"].append(
        {"text": "전화 02-1234-5678", "evidence": _proof("전화 02-1234-5678")}
    )

    body, context = build_selection_request(parent, children)

    assert "02-1234-5678" not in str(body)
    assert "02-1234-5678" not in str(context)
    assert set(context["candidates"]) == {"C1", "C2"}


def test_selection_preserves_existing_claims_and_fills_only_empty_group():
    parent, children = _reports()
    original = deepcopy(children[0]["payload"]["groups"][0]["claims"])
    parent["payload"].pop("reportStatus")
    parent["payload"]["groups"][0]["claims"] = deepcopy(original)
    parent["payload"]["groups"][0]["summary"] = original[0]["text"]

    body, context = build_selection_request(parent, children)
    assert set(context["candidates"]) == {"C1"}
    assert (
        body["response_format"]["json_schema"]["schema"]["properties"]["selected"][
            "properties"
        ]["G1"]["maxItems"]
        == 0
    )

    report = materialize_evidence_selection(
        {"selected": {"G1": [], "G2": ["C1"]}}, context
    )
    assert report["groups"][0]["claims"] == original
    assert (
        report["groups"][1]["claims"] == children[1]["payload"]["groups"][0]["claims"]
    )


@pytest.mark.parametrize("partially_claimed", [False, True])
def test_enrichment_planner_enqueues_once_for_fixed_parent_version(
    tmp_path, partially_claimed
):
    store = GraphStore(tmp_path / "state")
    try:
        parent, children = _reports()
        if partially_claimed:
            parent["payload"].pop("reportStatus")
            parent["payload"]["groups"][0]["claims"] = deepcopy(
                children[0]["payload"]["groups"][0]["claims"]
            )
            parent["payload"]["groups"][0]["summary"] = "법안이 발의됐다."
        for child in children:
            store.put_artifact(
                "community",
                child["key"],
                {"group_id_version": GROUP_ID_VERSION},
                child["payload"],
            )
        current_children = [
            store.get_artifact("community", child["key"]) for child in children
        ]
        parent["dependency"]["children"] = [
            {"kind": "community", "key": child["key"], "version": child["version"]}
            for child in current_children
        ]
        store.put_artifact(
            "community", parent["key"], parent["dependency"], parent["payload"]
        )

        assert plan_evidence_enrichments(store, "model@revision", 5) == 1
        assert plan_evidence_enrichments(store, "model@revision", 5) == 0
        jobs = store.jobs(kind="community")
        assert len(jobs) == 1
        assert (
            jobs[0]["context"]["prior_report_version"]
            == store.get_artifact("community", parent["key"])["version"]
        )
        assert jobs[0]["context"]["output_contract"].endswith("selection-v1")
    finally:
        store.close()


def _queued_enrichment(tmp_path) -> tuple[GraphStore, Factory, dict]:
    store = GraphStore(tmp_path / "state")
    parent, children = _reports()
    for child in children:
        store.put_artifact(
            "community",
            child["key"],
            {"group_id_version": GROUP_ID_VERSION},
            child["payload"],
        )
    parent["dependency"]["children"] = [
        {
            "kind": "community",
            "key": child["key"],
            "version": store.get_artifact("community", child["key"])["version"],
        }
        for child in children
    ]
    store.put_artifact(
        "community", parent["key"], parent["dependency"], parent["payload"]
    )
    assert plan_evidence_enrichments(store, "model@revision", 5) == 1
    factory = Factory(store, None, "model@revision")
    return store, factory, parent


def _selected_response() -> dict:
    return {
        "request_id": "remote-1",
        "_modelMetadata": {"actual_model": "model", "revision": "revision"},
        "result": {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": json.dumps(
                            {"selected": {"G1": ["C1"], "G2": ["C2"]}}
                        )
                    },
                }
            ]
        },
    }


def test_completed_selection_projects_new_community_version(tmp_path):
    store, factory, parent = _queued_enrichment(tmp_path)
    try:
        job = store.claim(factory.owner, lease_seconds=120, limit=1)[0]
        job = store.checkpoint(
            job["id"], factory.owner, state="submitting", remote_id="remote-1"
        )
        previous = store.get_artifact("community", parent["key"])

        factory._complete(job, _selected_response(), time.time())

        current = store.get_artifact("community", parent["key"])
        assert store.get_job(job["id"])["state"] == "completed"
        assert current["version"] != previous["version"]
        assert current["payload"]["reportStatus"] == "evidence_selected"
        assert len(current["payload"]["groups"][0]["claims"]) == 1
    finally:
        store.close()


def test_changed_parent_version_obsoletes_inflight_selection(tmp_path):
    store, factory, parent = _queued_enrichment(tmp_path)
    try:
        job = store.claim(factory.owner, lease_seconds=120, limit=1)[0]
        job = store.checkpoint(
            job["id"], factory.owner, state="submitting", remote_id="remote-1"
        )
        changed = deepcopy(parent["payload"])
        changed["groups"][0]["title"] = "새 분류"
        store.put_artifact("community", parent["key"], parent["dependency"], changed)
        latest = store.get_artifact("community", parent["key"])

        factory._complete(job, _selected_response(), time.time())

        assert store.get_job(job["id"])["state"] == "obsolete"
        assert (
            store.get_artifact("community", parent["key"])["version"]
            == latest["version"]
        )
    finally:
        store.close()


def test_failed_selection_retries_same_id_only_contract(tmp_path):
    store, factory, _ = _queued_enrichment(tmp_path)
    try:
        first = store.claim(factory.owner, lease_seconds=120, limit=1)[0]
        store.release(
            first["id"],
            factory.owner,
            state="failed",
            error="generated_content_validation_failed",
            metadata={"completion_uncertain": False},
        )

        assert plan_output_retries(store, "model@revision", 5) == 1
        retries = [
            job for job in store.jobs(kind="community") if job["id"] != first["id"]
        ]
        assert len(retries) == 1
        assert (
            retries[0]["context"]["output_contract"]
            == first["context"]["output_contract"]
        )
        assert (
            retries[0]["request"]["response_format"]
            == first["request"]["response_format"]
        )
        assert (
            retries[0]["context"]["prior_report_version"]
            == first["context"]["prior_report_version"]
        )
    finally:
        store.close()


def test_same_named_community_group_in_distinct_reports_has_distinct_identity():
    output = {
        "groups": [
            {"title": "동일한 주제", "members": ["E1"], "summary": "", "claims": []}
        ]
    }
    context = {"level": 0, "aliases": {"E1": {"id": "person-a"}}, "units": {}}

    first = validate_report(output, context | {"artifact_key": "leaf:source-a"})[
        "groups"
    ][0]["id"]
    second = validate_report(output, context | {"artifact_key": "leaf:source-b"})[
        "groups"
    ][0]["id"]

    assert first != second


def test_old_unscoped_community_revision_is_not_current():
    assert routing_current("community", {"children": []}) is False
    assert (
        routing_current(
            "community", {"children": [], "group_id_version": GROUP_ID_VERSION}
        )
        is True
    )
