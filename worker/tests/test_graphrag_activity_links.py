"""Official activity links require remote judgment and fixed source proof."""

import time

from test_graphrag_engine import SIGNATURE
from test_graphrag_inputs import fixture_batch
from test_graphrag_lineage_repair import completed_reply

from parliament_worker.graphrag.activity_repair import (
    plan_activity_links,
    validate_activity_link,
)
from parliament_worker.graphrag.activity_sources import project_activity_roles
from parliament_worker.graphrag.engine import Factory
from parliament_worker.graphrag.index import graph_view
from parliament_worker.graphrag.inputs import sources_from_batch
from parliament_worker.graphrag.policy import apply_review_policy
from parliament_worker.graphrag.store import GraphStore


def _source():
    batch = fixture_batch()
    document = batch["documents"][0]
    document["sourceKey"] = "ministry-press-release"
    document["recordKey"] = "briefing-1"
    document["sourceUrl"] = "https://www.mogef.go.kr/nw/rpd/example"
    text = "성평등가족부는 김가 장관 주재 정책 간담회를 개최할 예정이다."
    document["segments"][0]["text"] = text
    batch["evidence"][0]["end"] = len(text)
    batch["entities"].append(
        {
            "id": "org-a",
            "kind": "organization",
            "name": "성평등가족부",
            "identifiers": [],
            "facts": [],
            "tenures": [],
        }
    )
    batch["activities"] = [
        {
            "id": "act-a",
            "title": "정책 간담회",
            "type": "announcement",
            "stage": "scheduled",
            "version": "activity-v1",
            "sourceUrl": document["sourceUrl"],
        }
    ]
    batch["relations"] = [
        {
            "id": f"relation-{actor}",
            "type": relation_type,
            "subjectId": actor,
            "objectId": "act-a",
            "evidenceIds": ["ev-a"],
            "decision": "pending",
        }
        for relation_type, actor in (
            ("scheduled_participant", "p-a"),
            ("publisher", "org-a"),
        )
    ]
    return sources_from_batch(batch)[0]


def test_activity_roles_enqueue_two_fixed_source_model_checks(tmp_path) -> None:
    """The server receives the selected proof and a distinct task per role."""
    store = GraphStore(tmp_path / "state")
    store.put_sources([_source()])

    assert plan_activity_links(store, SIGNATURE, 10) == 2
    jobs = store.jobs(kind="extract")
    assert {job["context"]["candidate"]["type"] for job in jobs} == {
        "publisher",
        "scheduled_participant",
    }
    assert all(job["state"] == "planned" for job in jobs)
    assert all(job["context"]["source_units"] for job in jobs)
    assert len({job["idempotency_key"] for job in jobs}) == 2
    assert plan_activity_links(store, SIGNATURE, 10) == 0


def test_rejected_source_role_is_never_offered_for_model_check() -> None:
    """Human-rejected role evidence must not re-enter the candidate graph."""
    payload = _source()["payload"]
    unit = payload["units"][0]
    activity = payload["activityCandidates"][0]
    actor = next(item for item in payload["entities"] if item["id"] == "org-a")
    batch = {
        "activities": [
            {
                **activity,
                "title": activity["name"],
                "sourceUrl": payload["document"]["sourceUrl"],
            }
        ],
        "relations": [
            {
                "type": "publisher",
                "subjectId": actor["id"],
                "objectId": activity["id"],
                "evidenceIds": ["ev-rejected"],
                "decision": "rejected",
            }
        ],
    }
    evidence = {**unit, "id": "ev-rejected"}

    assert (
        project_activity_roles(
            batch,
            payload["document"],
            [evidence],
            payload["units"],
            {actor["id"]: actor},
        )
        == {}
    )


def test_activity_role_result_remains_private_and_requires_human_review(
    tmp_path,
) -> None:
    """A positive model result never publishes a person's planned attendance."""
    store = GraphStore(tmp_path / "state")
    store.put_sources([_source()])
    assert plan_activity_links(store, SIGNATURE, 10) == 2
    job = next(
        item
        for item in store.jobs(kind="extract")
        if item["context"]["candidate"]["type"] == "scheduled_participant"
    )
    source = store.sources()[0]

    graph = apply_review_policy(
        validate_activity_link({"supported": True}, job["context"], source)
    )

    assert graph["public"] is False
    assert {node["kind"] for node in graph["nodes"]} == {"person", "activity"}
    assert graph["edges"][0]["type"] == "scheduled_participant"
    assert graph["edges"][0]["decision"] == "pending"
    assert "human_role_review" in graph["edges"][0]["publicationBlockedBy"]
    assert graph["edges"][0]["evidence"] == job["context"]["source_units"]
    assert (
        validate_activity_link({"supported": False}, job["context"], source)["edges"]
        == []
    )


def test_factory_plans_and_projects_official_activity_role(tmp_path) -> None:
    """The running factory must execute the specialized proof contract."""
    store = GraphStore(tmp_path / "state")
    store.put_sources([_source()])
    factory = Factory(store, None, SIGNATURE)
    factory.plan()
    claimed = store.claim(factory.owner, lease_seconds=600, limit=20)
    job = next(
        item
        for item in claimed
        if item["context"].get("relation_task") == "activity_role"
        and item["context"]["candidate"]["type"] == "scheduled_participant"
    )
    job = store.checkpoint(job["id"], factory.owner, state="submitting")

    factory._complete(job, completed_reply(True), time.time())

    graph = store.get_artifact("graph", job["context"]["artifact_key"])
    assert graph is not None
    assert graph["payload"]["edges"][0]["decision"] == "pending"
    assert graph["payload"]["public"] is False
    view = graph_view(store, root="p-a")
    assert {node["kind"] for node in view["nodes"]} >= {"person", "activity"}
    assert any(edge["type"] == "scheduled_participant" for edge in view["edges"])
    assert view["private"] is True
