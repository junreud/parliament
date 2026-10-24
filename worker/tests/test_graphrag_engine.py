"""The graph, community hierarchy and grounded queries survive incremental changes."""

import json
from copy import deepcopy
from datetime import datetime, timezone

import pytest
from test_graphrag_inputs import fixture_batch

from parliament_worker.graphrag.client import InferenceError
from parliament_worker.graphrag.engine import Factory
from parliament_worker.graphrag.index import (
    current_artifacts,
    graph_view,
    plan_communities,
    reconcile,
    source_dependency,
)
from parliament_worker.graphrag.inputs import fingerprint, sources_from_batch
from parliament_worker.graphrag.prompts import GROUP_ID_VERSION, PROMPT_VERSION
from parliament_worker.graphrag.query import question_status, submit_question
from parliament_worker.graphrag.store import GraphStore

SIGNATURE = "test-model@test-revision"


class RemoteFixture:
    """An idempotent fake remote queue with fixed evidence-grounded output."""

    def __init__(self):
        self.accepted = {}
        self.submissions = []
        self.lose_response = False
        self.model = {"actual_model": "test-model", "revision": "test-revision"}

    def submit(self, body, key):
        self.submissions.append((key, deepcopy(body)))
        self.accepted.setdefault(key, body)
        if self.lose_response:
            self.lose_response = False
            raise InferenceError(
                "lost_submission_response", retryable=True, uncertain=True
            )
        return {"request_id": key, "state": "queued"}

    def poll(self, key):
        body = self.accepted[key]
        payload = json.loads(body["messages"][1]["content"])
        task = payload["task"]
        if task.startswith("extract"):
            aliases = {item["kind"]: item["id"] for item in payload["known"]}
            output = {
                "entities": [],
                "relations": [
                    {
                        "s": aliases["person"],
                        "t": aliases["bill"],
                        "type": "lead_sponsor",
                        "unit": "U1",
                        "quote": payload["source"]["U1"],
                    }
                ],
            }
        elif task.startswith("assign"):
            sources = payload["sources"]
            unit = next(iter(sources))
            output = {
                "groups": [
                    {
                        "title": "법안 발의",
                        "members": [item["id"] for item in payload["members"]],
                        "summary": "공식 법안 발의 기록",
                        "claims": [
                            {
                                "text": "김가 의원의 법안 대표발의 기록",
                                "unit": unit,
                                "quote": sources[unit],
                            }
                        ],
                    }
                ]
            }
        else:
            unit = next(iter(payload["sources"]))
            answer_schema = (
                body.get("response_format", {}).get("json_schema", {}).get("name")
            )
            proof = (
                {"proof": unit}
                if answer_schema
                in {"parliament_answer_selector_v2", "parliament_answer_claims_v3"}
                else {"unit": unit, "quote": payload["sources"][unit]}
            )
            output = {
                "claims": [
                    {
                        "text": "김가 의원은 새 법안을 대표발의했다.",
                        **proof,
                    }
                ],
            }
            if answer_schema != "parliament_answer_claims_v3":
                output["insufficient"] = False
        return {
            "state": "completed",
            "_modelMetadata": self.model,
            "result": {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(output, ensure_ascii=False)},
                    }
                ]
            },
        }


def make_factory(tmp_path):
    store = GraphStore(tmp_path / "state")
    source = sources_from_batch(fixture_batch())[0]
    store.put_sources([source])
    client = RemoteFixture()
    return Factory(store, client, SIGNATURE, poll_seconds=0.1), source


def test_same_source_reobservation_is_saved_without_new_graph_generation(tmp_path):
    batch = fixture_batch()
    batch["documents"][0]["observedAt"] = "2026-10-16T12:00:00+00:00"
    path = tmp_path / "input.json"
    path.write_text(json.dumps(batch, ensure_ascii=False), encoding="utf-8")
    store = GraphStore(tmp_path / "state")
    factory = Factory(store, RemoteFixture(), SIGNATURE)

    assert factory.sync_inputs([path])["changed"] == 1
    source = store.sources()[0]
    assert store.source_observation_times()[source["scope"]] == (
        "2026-10-16T12:00:00+00:00"
    )

    batch["documents"][0]["observedAt"] = "2026-10-17T12:00:00+00:00"
    batch["id"] = "batch-reobserved"
    path.write_text(json.dumps(batch, ensure_ascii=False), encoding="utf-8")
    assert factory.sync_inputs([path])["changed"] == 0
    assert store.sources()[0]["generation"] == source["generation"]
    assert store.source_observation_times()[source["scope"]] == (
        "2026-10-17T12:00:00+00:00"
    )

    batch["documents"][0]["observedAt"] = "2026-10-17T08:00:00-05:00"
    path.write_text(json.dumps(batch, ensure_ascii=False), encoding="utf-8")
    assert factory.sync_inputs([path])["changed"] == 0
    assert store.source_observation_times()[source["scope"]] == (
        "2026-10-17T13:00:00+00:00"
    )


def test_temporal_question_reports_collection_time_separately_from_answer(tmp_path):
    batch = fixture_batch()
    batch["documents"][0]["observedAt"] = "2026-10-17T10:00:00+00:00"
    source = sources_from_batch(batch)[0]
    store = GraphStore(tmp_path / "state")
    store.put_sources([source])
    submitted = submit_question(
        store,
        "김가 의원의 현재 재임 여부와 관측 시점은?",
        "local",
        SIGNATURE,
    )
    question = question_status(store, submitted["id"])

    assert question["retrieval"]["includedProofs"] >= 1
    assert question["sourceObservations"] == [
        {
            "sourceUrl": "https://www.assembly.go.kr/example",
            "observedAt": "2026-10-17T10:00:00+00:00",
            "meaning": "collection_time_only",
        }
    ]

    store.record_source_observations(
        [{**source, "observedAt": "2026-10-17T11:00:00+00:00"}]
    )
    refreshed = question_status(store, submitted["id"])
    assert refreshed["sourceObservations"][0]["observedAt"] == (
        "2026-10-17T11:00:00+00:00"
    )
    assert refreshed["outdatedIndex"] is False


def drain(factory, cycles=20):
    for _ in range(cycles):
        factory.plan()
        for job in factory.store.jobs():
            if job["state"] in {"polling", "deferred", "planned"}:
                factory.store.update_job(job["id"], next_poll=0)
        factory.tick(8)
        factory.plan()
        if not any(
            job["state"] in {"planned", "submitting", "polling", "deferred"}
            for job in factory.store.jobs()
        ):
            return
    raise AssertionError("fixture did not drain")


def test_changed_and_removed_sources_withdraw_graph_and_old_answers_immediately(
    tmp_path,
):
    factory, source = make_factory(tmp_path)
    drain(factory)
    question = submit_question(factory.store, "김가 법안?", "local", SIGNATURE)
    drain(factory)
    changed = deepcopy(source)
    changed["payload"]["document"]["version"] = "version-b"
    changed["payload"]["units"][0]["documentVersion"] = "version-b"
    changed["fingerprint"] = fingerprint(changed["payload"])
    factory.store.put_sources([changed])
    assert graph_view(factory.store)["edges"] == []
    assert current_artifacts(factory.store, "community") == []
    assert question_status(factory.store, question["id"])["state"] == "obsolete"
    reconcile(factory.store)
    drain(factory)
    assert (
        graph_view(factory.store)["edges"][0]["evidence"][0]["documentVersion"]
        == "version-b"
    )
    history = factory.store.artifacts("graph", current=False)
    assert any(
        artifact["payload"]["edges"][0]["evidence"][0]["documentVersion"] == "version-a"
        for artifact in history
    )
    factory.store.retire_source(source["scope"])
    assert graph_view(factory.store)["nodes"] == []
    assert current_artifacts(factory.store, "community") == []


def test_recovery_does_not_republish_intentionally_retired_history(tmp_path):
    factory, _ = make_factory(tmp_path)
    drain(factory)
    store = factory.store
    report = store.artifacts("community")[0]
    store.invalidate_artifact("community", report["key"])
    assert store.get_artifact("community", report["key"]) is None

    factory.recover_projections()

    assert store.get_artifact("community", report["key"]) is None
    assert len(store.artifact_versions("community", report["key"])) == 1


def test_recovery_projects_only_a_completed_result_without_saved_version(tmp_path):
    factory, _ = make_factory(tmp_path)
    drain(factory)
    store = factory.store
    report = store.artifacts("community")[0]
    with store._transaction() as db:
        db.execute(
            "DELETE FROM artifacts WHERE kind=? AND artifact_key=?",
            ("community", report["key"]),
        )

    factory.recover_projections()

    restored = store.get_artifact("community", report["key"])
    assert restored is not None
    assert restored["version"] == report["version"]


def test_recovery_removes_legacy_edges_with_wrong_endpoint_kinds(tmp_path):
    factory, _ = make_factory(tmp_path)
    factory.plan()
    store = factory.store
    job = store.jobs(kind="extract")[0]
    nodes = [
        {"id": "p-a", "kind": "person", "name": "김가"},
        {"id": "b-a", "kind": "bill", "name": "새 법안"},
    ]
    legacy = {
        "nodes": nodes,
        "edges": [
            {"id": "good", "source": "p-a", "target": "b-a", "type": "lead_sponsor"},
            {"id": "bad", "source": "p-a", "target": "b-a", "type": "speaker"},
        ],
        "public": False,
    }
    store.update_job(job["id"], state="submitting")
    store.update_job(job["id"], state="completed", result=legacy)
    dependency = {
        key: job["context"][key]
        for key in ("sources", "model_signature", "prompt_version")
    }
    old_version = store.put_artifact(
        "graph", job["context"]["artifact_key"], dependency, legacy
    )

    factory.recover_projections()

    current = store.get_artifact("graph", job["context"]["artifact_key"])
    assert current["version"] != old_version
    assert [edge["id"] for edge in current["payload"]["edges"]] == ["good"]
    assert len(store.artifact_versions("graph", current["key"])) == 2
    assert len(store.get_job(job["id"])["result"]["edges"]) == 2


def test_new_person_source_does_not_regenerate_unrelated_extraction(tmp_path):
    factory, _ = make_factory(tmp_path)
    drain(factory)
    old_extract = [job["id"] for job in factory.store.jobs(kind="extract")]
    batch = fixture_batch()
    batch["documents"][0]["recordKey"] = "3"
    batch["entities"][0]["id"] = "p-other"
    new = sources_from_batch(batch)[0]
    factory.store.put_sources([new])
    drain(factory)
    assert len(factory.store.jobs(kind="extract")) == 2
    assert factory.store.get_job(old_extract[0])["state"] == "completed"
    assert len(factory.client.accepted) == len(factory.store.jobs(state="completed"))
    assert any(
        artifact["payload"]["level"] == 1
        for artifact in current_artifacts(factory.store, "community")
    )


def test_old_group_ids_are_retired_without_reextracting_sources(tmp_path):
    factory, _ = make_factory(tmp_path)
    drain(factory)
    graph = current_artifacts(factory.store, "graph")[0]
    leaf = current_artifacts(factory.store, "community")[0]
    store = GraphStore(tmp_path / "migration-state")
    store.put_sources(factory.store.sources())
    store.put_artifact("graph", graph["key"], graph["dependency"], graph["payload"])
    old_dependency = {
        key: value
        for key, value in leaf["dependency"].items()
        if key != "group_id_version"
    }
    store.put_artifact("community", leaf["key"], old_dependency, leaf["payload"])

    assert reconcile(store) >= 1
    assert store.get_artifact("community", leaf["key"]) is None
    assert store.get_artifact("graph", graph["key"])["version"] == graph["version"]
    assert len(store.artifact_versions("community", leaf["key"])) == 1
    assert plan_communities(store, SIGNATURE) == 1
    assert store.jobs()[-1]["context"]["group_id_version"] == GROUP_ID_VERSION


def test_old_group_id_contract_makes_pinned_question_outdated(tmp_path):
    factory, _ = make_factory(tmp_path)
    drain(factory)
    store = factory.store
    question = submit_question(store, "공식 법안 기록은?", "local", SIGNATURE)
    assert question_status(store, question["id"])["outdatedIndex"] is False
    leaf = current_artifacts(store, "community")[0]
    old_dependency = {
        key: value
        for key, value in leaf["dependency"].items()
        if key != "group_id_version"
    }
    store.put_artifact("community", leaf["key"], old_dependency, leaf["payload"])

    status = question_status(store, question["id"])
    assert status["outdatedIndex"] is True
    assert status["state"] != "obsolete"
    assert current_artifacts(store, "graph")


def test_empty_graph_unit_does_not_block_parent_communities(tmp_path):
    factory, _ = make_factory(tmp_path)
    drain(factory)
    store = factory.store
    first_graph = current_artifacts(store, "graph")[0]
    first_leaf = current_artifacts(store, "community")[0]
    for number, empty in ((3, False), (4, True)):
        batch = fixture_batch()
        batch["documents"][0]["recordKey"] = str(number)
        batch["entities"][0]["id"] = f"p-{number}"
        source = sources_from_batch(batch)[0]
        store.put_sources([source])
        key = source["scope"] + ":" + source["payload"]["units"][0]["id"]
        dependency = {
            "sources": [source_dependency(store.sources()[-1])],
            "model_signature": SIGNATURE,
            "prompt_version": PROMPT_VERSION,
        }
        payload = (
            {"nodes": [], "edges": [], "public": False}
            if empty
            else first_graph["payload"]
        )
        version = store.put_artifact("graph", key, dependency, payload)
        if not empty:
            leaf_key = f"leaf:{fingerprint(source['scope'])[:2]}:{fingerprint(key)}"
            store.put_artifact(
                "community",
                leaf_key,
                {
                    **dependency,
                    "group_id_version": GROUP_ID_VERSION,
                    "children": [{"kind": "graph", "key": key, "version": version}],
                },
                first_leaf["payload"],
            )
    assert plan_communities(store, SIGNATURE) == 1
    assert store.jobs()[-1]["context"]["artifact_key"].startswith("parent:1:")


def test_lost_submission_response_never_resubmits_after_restart_or_resume(tmp_path):
    factory, _ = make_factory(tmp_path)
    factory.client.lose_response = True
    factory.plan()
    factory.tick(1)
    job = factory.store.jobs()[0]
    assert job["state"] == "deferred" and job["remote_id"] is None
    assert factory.store.get_artifact("control", "pause") is not None
    factory.store.update_job(job["id"], next_poll=0)
    restarted = Factory(
        GraphStore(tmp_path / "state"), factory.client, SIGNATURE, poll_seconds=0.1
    )
    restarted.tick(1)
    assert len(factory.client.accepted) == 1
    assert len(factory.client.submissions) == 1
    restarted.resume()
    restarted.tick(1)
    assert len(factory.client.submissions) == 1
    assert restarted.store.get_artifact("control", "pause") is not None
    assert restarted.store.get_job(job["id"])["request"] == job["request"]
    assert (
        restarted.store.get_job(job["id"])["idempotency_key"] == job["idempotency_key"]
    )


def test_lost_poll_response_keeps_polling_existing_id_without_submission(tmp_path):
    factory, _ = make_factory(tmp_path)
    factory.plan()
    factory.tick(1)
    job = factory.store.jobs()[0]
    original = factory.client.poll

    def lost_response(_key):
        raise InferenceError("lost_poll_response", retryable=True, uncertain=True)

    factory.client.poll = lost_response
    factory.store.update_job(job["id"], next_poll=0)
    factory.tick(1)
    assert factory.store.get_artifact("control", "pause") is None
    assert factory.store.get_job(job["id"])["remote_id"] == job["remote_id"]
    factory.client.poll = original
    factory.store.update_job(job["id"], next_poll=0)
    factory.tick(1)
    assert factory.store.get_job(job["id"])["state"] == "completed"
    assert len(factory.client.submissions) == 1


@pytest.mark.parametrize("concurrency", [16, 32, 64])
def test_requests_overlap_without_exceeding_inflight_limit(tmp_path, concurrency):
    store = GraphStore(tmp_path / "parallel-state")
    for index in range(concurrency + 4):
        batch = fixture_batch()
        batch["documents"][0]["recordKey"] = str(index)
        store.put_sources(sources_from_batch(batch))
    remote = RemoteFixture()
    factory = Factory(
        store, remote, SIGNATURE, concurrency=concurrency, poll_seconds=60
    )
    factory.plan()
    factory.tick(max(32, concurrency))
    assert len(remote.submissions) == concurrency
    inflight = [job for job in store.jobs() if job["state"] == "polling"]
    assert len(inflight) == concurrency
    factory.tick(max(32, concurrency))
    assert len(remote.submissions) == concurrency


def test_concurrency_above_local_dispatch_limit_is_rejected(tmp_path):
    factory, _ = make_factory(tmp_path)
    with pytest.raises(ValueError, match="execution limits"):
        Factory(factory.store, factory.client, SIGNATURE, concurrency=65)


@pytest.mark.parametrize(
    "daily_jobs,daily_tokens,expected_submissions",
    [(0, 0, 1), (1, 0, 0), (0, 4096, 0)],
)
def test_zero_disables_only_selected_daily_limits(
    tmp_path, daily_jobs, daily_tokens, expected_submissions
):
    original, _ = make_factory(tmp_path)
    previous = original.store.enqueue("extract", "previous-work", {}, {})
    original.store.update_job(
        previous,
        state="failed",
        metadata={
            "submitted_day": datetime.now(timezone.utc).date().isoformat(),
            "reserved_tokens": 4096,
        },
    )
    factory = Factory(
        original.store,
        original.client,
        SIGNATURE,
        daily_jobs=daily_jobs,
        daily_tokens=daily_tokens,
    )
    factory.plan()
    factory.tick(8)
    assert len(factory.client.submissions) == expected_submissions


def test_auth_failure_and_model_switch_pause_new_requests(tmp_path):
    factory, _ = make_factory(tmp_path)
    factory.plan()
    factory.tick(1)
    job = factory.store.jobs()[0]
    factory.store.update_job(job["id"], next_poll=0)
    factory.client.model["revision"] = "changed-model"
    factory.tick(1)
    assert factory.store.get_job(job["id"])["error"] == "model_revision_mismatch"
    assert factory.tick(4) == 0


def test_machine_general_approval_does_not_approve_personal_action():
    from parliament_worker.graphrag.policy import apply_review_policy

    nodes = [
        {
            "id": "a",
            "kind": "bill",
            "identityStatus": "source_bound",
            "identifiers": [1],
        },
        {
            "id": "b",
            "kind": "policy",
            "identityStatus": "source_bound",
            "identifiers": [2],
        },
    ]
    evidence = [{"licenseStatus": "allowed"}]
    graph = apply_review_policy(
        {
            "nodes": nodes,
            "edges": [
                {
                    "source": "a",
                    "target": "b",
                    "type": "concerns",
                    "evidence": evidence,
                    "endpointSupported": True,
                    "relationCueSupported": True,
                }
            ],
        }
    )
    assert graph["edges"][0]["decision"] == "approved"
    assert graph["edges"][0]["reviewRequired"] is False
    graph["edges"][0]["type"] = "voter"
    assert apply_review_policy(graph)["edges"][0]["decision"] == "pending"
