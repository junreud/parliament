"""Global answers must not lose source facts omitted by graph reports."""

import json
from copy import deepcopy

import pytest
from test_graphrag_engine import SIGNATURE, drain, make_factory
from test_graphrag_inputs import fixture_batch

from parliament_worker.graphrag.answer_requests import community_answer_requests
from parliament_worker.graphrag.index import graph_view
from parliament_worker.graphrag.inputs import fingerprint, sources_from_batch
from parliament_worker.graphrag.query import (
    _local_context,
    question_status,
    submit_question,
)
from parliament_worker.graphrag.store import GraphStore


def test_local_answer_keeps_source_quote_out_of_claim_text(tmp_path) -> None:
    """The UI claim should cite a separate proof instead of repeating its quote."""
    factory, _ = make_factory(tmp_path)
    drain(factory)
    question = submit_question(factory.store, "김가 의원의 법안은?", "local", SIGNATURE)
    job = next(
        item
        for item in factory.store.jobs(kind="query_local")
        if item["context"]["question_id"] == question["id"]
    )
    prompt = json.loads(job["request"]["messages"][-1]["content"])
    assert "Do not repeat the source quote in claim text" in prompt["rules"]
    claim_schema = job["request"]["response_format"]["json_schema"]["schema"][
        "properties"
    ]["claims"]["items"]["properties"]
    assert "proof" in claim_schema


def test_local_proof_selection_uses_the_final_answer_prompt_budget(tmp_path) -> None:
    """A boundary-length excerpt must not pass preflight and fail on enqueue."""
    batch = fixture_batch()
    passage = ("김가 " * 167)[:500]
    batch["documents"][0]["segments"][0]["text"] = passage
    batch["evidence"][0]["end"] = len(passage)
    store = GraphStore(tmp_path / "state")
    store.put_sources(sources_from_batch(batch))

    question = submit_question(
        store, "김가 인물의 공식 기록은?", "local", SIGNATURE, entity_id="p-a"
    )
    status = question_status(store, question["id"])

    assert question["state"] == "queued"
    assert status["retrieval"]["includedProofs"] == 1
    assert len(store.jobs(kind="query_local")) == 1


def test_person_role_question_excludes_name_and_city_only_excerpt(tmp_path) -> None:
    """A directory label alone cannot answer a person's office or activity."""
    batch = fixture_batch()
    passage = "경기도 화성시 김가"
    batch["documents"][0]["segments"][0]["text"] = passage
    batch["evidence"][0]["end"] = len(passage)
    store = GraphStore(tmp_path / "state")
    store.put_sources(sources_from_batch(batch))

    proofs, _, retrieval = _local_context(
        store,
        "김가 인물과 공식 기록에서 확인되는 직위 또는 활동 관계는 무엇인가요?",
        entity_id="p-a",
    )

    assert proofs == []
    assert retrieval["weakRoleProofsExcluded"] == 1
    question = submit_question(
        store,
        "김가 인물과 공식 기록에서 확인되는 직위 또는 활동 관계는 무엇인가요?",
        "local",
        SIGNATURE,
        entity_id="p-a",
    )
    assert question["state"] == "insufficient_evidence"
    assert not store.jobs(kind="query_local")


def test_person_activity_question_retains_new_action_vocabulary(tmp_path) -> None:
    """A specific action stays retrievable even if no action word was prelisted."""
    batch = fixture_batch()
    passage = "김가 씨는 국정감사 질의서를 제출했다."
    batch["documents"][0]["segments"][0]["text"] = passage
    batch["evidence"][0]["end"] = len(passage)
    store = GraphStore(tmp_path / "state")
    store.put_sources(sources_from_batch(batch))

    proofs, _, retrieval = _local_context(
        store,
        "김가 인물의 활동은 무엇인가요?",
        entity_id="p-a",
    )

    assert [proof["text"] for proof in proofs] == [passage]
    assert retrieval["weakRoleProofsExcluded"] == 0


def test_global_question_maps_reports_and_every_current_source_unit(tmp_path) -> None:
    """A graph-free official document remains available to global questions."""
    factory, original = make_factory(tmp_path)
    drain(factory)
    other = deepcopy(original)
    other["scope"] = "ministry-program-guide:example"
    other["payload"]["document"]["id"] = "doc-program-guide"
    other["payload"]["document"]["title"] = "양육비 선지급제 안내"
    other["payload"]["entities"] = []
    other["payload"]["units"][0].update(
        id="guide-unit",
        documentId="doc-program-guide",
        text="양육비 선지급제는 2025. 7. 1. 시행한다.",
        start=0,
        end=len("양육비 선지급제는 2025. 7. 1. 시행한다."),
    )
    other["fingerprint"] = fingerprint(other["payload"])
    factory.store.put_sources([other])

    question = submit_question(
        factory.store, "양육비 선지급제의 시행 시점은?", "global", SIGNATURE
    )
    status = question_status(factory.store, question["id"])
    jobs = factory.store.jobs(kind="query_map")
    source_jobs = [
        job
        for job in jobs
        if "doc-program-guide"
        in {unit["documentId"] for unit in job["context"]["units"].values()}
    ]
    assert len(source_jobs) == 1
    assert json.loads(source_jobs[0]["request"]["messages"][-1]["content"])[
        "sources"
    ] == {"S1": "양육비 선지급제는 2025. 7. 1. 시행한다."}
    assert status["retrieval"]["sourceUnits"] == 2
    assert status["retrieval"]["sourceMapTasks"] == 2
    assert status["retrieval"]["mapTasks"] == len(jobs)


def test_oversized_community_group_keeps_every_proof() -> None:
    """Long report groups are split without omitting either cited excerpt."""
    question = "양육비 선지급제의 원안·대안·정부 후속 발표에서 각각 무엇이 기록됐나?"
    proofs = [{"text": "가" * 250}, {"text": "나" * 250}]
    context = [{"title": "양육비 선지급제", "summary": "요약" * 20}]

    batches = community_answer_requests(question, proofs, context)

    assert len(batches) == 2
    assert [unit["text"] for _, ctx in batches for unit in ctx["units"].values()] == [
        proof["text"] for proof in proofs
    ]


def test_local_context_does_not_repeat_same_graph_and_source_excerpt(tmp_path) -> None:
    """A graph edge and its full source unit share one context slot."""
    factory, _ = make_factory(tmp_path)
    drain(factory)

    proofs, _, retrieval = _local_context(
        factory.store,
        "김가 의원이 새 법안에 어떤 역할을 했나?",
        entity_id="p-a",
    )

    assert len(proofs) == 1
    assert retrieval["retrievedProofs"] == 1
    assert proofs[0]["documentId"] == "doc-a"


def test_local_answer_context_omits_pending_edges_and_derived_reports(tmp_path) -> None:
    """Unreviewed graph prose cannot turn a name-only excerpt into a role fact."""
    factory, _ = make_factory(tmp_path)
    drain(factory)

    proofs, context, retrieval = _local_context(
        factory.store,
        "김가 의원이 어떤 직책을 맡고 있나?",
        entity_id="p-a",
    )

    assert proofs
    assert retrieval["graphEdges"] == 1
    assert context == []

    graph = factory.store.artifacts("graph")[0]
    approved = deepcopy(graph["payload"])
    approved["edges"][0]["decision"] = "approved"
    factory.store.put_artifact("graph", graph["key"], graph["dependency"], approved)
    _, approved_context, _ = _local_context(
        factory.store,
        "김가 의원이 어떤 직책을 맡고 있나?",
        entity_id="p-a",
    )
    assert len(approved_context) == 1
    assert approved_context[0]["role"] == "lead_sponsor"
    assert approved_context[0]["decision"] == "approved"


def test_source_only_person_is_known_without_inventing_graph_evidence(tmp_path) -> None:
    """A restricted profile remains a private known identity with no claims."""
    store = GraphStore(tmp_path / "state")
    source = sources_from_batch(fixture_batch())[0]
    source["payload"]["units"] = []
    source["payload"]["document"]["licenseStatus"] = "restricted"
    source["fingerprint"] = fingerprint(source["payload"])
    store.put_sources([source])

    graph = graph_view(store, root="p-a")
    question = submit_question(
        store, "김가 의원의 역할은?", "local", SIGNATURE, entity_id="p-a"
    )

    assert graph["private"] is True
    assert graph["nodes"] == [
        {
            "id": "p-a",
            "kind": "person",
            "name": "김가",
            "identityStatus": "input_unverified",
            "decision": "pending",
            "sourceOnly": True,
        }
    ]
    assert graph["edges"] == []
    assert question["state"] == "insufficient_evidence"
    assert store.jobs(kind="query_local") == []


def test_scoped_graph_reports_all_source_only_people_without_showing_them(
    tmp_path,
) -> None:
    """A person view reports the whole private identity coverage gap."""
    store = GraphStore(tmp_path / "state")
    first = sources_from_batch(fixture_batch())[0]
    first["payload"]["units"] = []
    first["payload"]["document"]["licenseStatus"] = "restricted"
    first["fingerprint"] = fingerprint(first["payload"])
    second = deepcopy(first)
    second["scope"] = "assembly:3"
    second["payload"]["document"]["id"] = "doc-b"
    second_person = next(
        entity for entity in second["payload"]["entities"] if entity["kind"] == "person"
    )
    second_person["id"] = "p-b"
    second_person["name"] = "김나"
    second["fingerprint"] = fingerprint(second["payload"])
    store.put_sources([first, second])

    graph = graph_view(store, root="p-a")

    assert [node["id"] for node in graph["nodes"]] == ["p-a"]
    assert graph["coverage"]["source_only_nodes"] == 2


def test_conflicting_source_names_do_not_resolve_one_person_id(tmp_path) -> None:
    """A typed ID collision stays visible for review and cannot answer queries."""
    store = GraphStore(tmp_path / "state")
    first = sources_from_batch(fixture_batch())[0]
    first["payload"]["units"] = []
    first["fingerprint"] = fingerprint(first["payload"])
    second = deepcopy(first)
    second["scope"] = "another:person-profile"
    next(entity for entity in second["payload"]["entities"] if entity["id"] == "p-a")[
        "name"
    ] = "김나"
    second["fingerprint"] = fingerprint(second["payload"])
    store.put_sources([first, second])

    graph = graph_view(store, root="p-a")

    assert graph["nodes"][0]["identityConflict"] is True
    with pytest.raises(ValueError, match="unknown scoped person"):
        submit_question(store, "법안 역할은?", "local", SIGNATURE, entity_id="p-a")


def test_global_source_maps_are_pinned_to_complete_source_set(tmp_path) -> None:
    """New source coverage uses the same compact revision guard as reports."""
    factory, _ = make_factory(tmp_path)
    drain(factory)
    question = submit_question(
        factory.store, "공식 기록의 주제는?", "global", SIGNATURE
    )
    status = question_status(factory.store, question["id"])
    maps = factory.store.jobs(kind="query_map")
    assert len(maps) == 2
    assert status["retrieval"]["communityMapTasks"] == 1
    assert status["retrieval"]["sourceMapTasks"] == 1
    assert all(len(job["context"]["source_manifest"]) == 64 for job in maps)
    assert all("sources" not in job["context"] for job in maps)


def test_global_question_can_read_a_source_before_graph_reports_exist(tmp_path) -> None:
    """A newly collected document is queryable while its graph is still pending."""
    store = GraphStore(tmp_path / "state")
    store.put_sources(sources_from_batch(fixture_batch()))
    question = submit_question(store, "공식 기록의 주제는?", "global", SIGNATURE)
    status = question_status(store, question["id"])
    assert status["state"] == "queued"
    assert status["retrieval"] == {
        "communityLevels": [],
        "reports": 0,
        "communityMapTasks": 0,
        "sourceUnits": 1,
        "sourceMapTasks": 1,
        "sensitiveUnitsExcluded": 0,
        "sensitiveCommunityProofsExcluded": 0,
        "qualityFlaggedCommunityClaimsExcluded": 0,
        "mapTasks": 1,
    }


def test_global_question_quarantines_contact_bearing_source_unit(tmp_path) -> None:
    """A raw map never forwards an unsanitized office contact field."""
    store = GraphStore(tmp_path / "state")
    source = sources_from_batch(fixture_batch())[0]
    source["payload"]["units"][0]["text"] += " 사무실 전화 02-123-4567"
    source["payload"]["units"][0]["end"] = len(source["payload"]["units"][0]["text"])
    source["fingerprint"] = fingerprint(source["payload"])
    store.put_sources([source])

    question = submit_question(store, "공식 기록의 주제는?", "global", SIGNATURE)
    status = question_status(store, question["id"])
    assert status["state"] == "insufficient_evidence"
    assert status["retrieval"]["sourceUnits"] == 1
    assert status["retrieval"]["sourceMapTasks"] == 0
    assert status["retrieval"]["sensitiveUnitsExcluded"] == 1
    assert store.jobs(kind="query_map") == []


def test_global_question_quarantines_public_postal_address(tmp_path) -> None:
    """A mailing address in a program guide is not sent in a new raw map."""
    store = GraphStore(tmp_path / "state")
    source = sources_from_batch(fixture_batch())[0]
    source["payload"]["units"][0][
        "text"
    ] += " (우편) 서울특별시 중구 퇴계로 173, 24층 담당자 앞"
    source["payload"]["units"][0]["end"] = len(source["payload"]["units"][0]["text"])
    source["fingerprint"] = fingerprint(source["payload"])
    store.put_sources([source])

    question = submit_question(store, "공식 기록의 주제는?", "global", SIGNATURE)
    status = question_status(store, question["id"])
    assert status["retrieval"]["sensitiveUnitsExcluded"] == 1
    assert status["retrieval"]["sourceMapTasks"] == 0
    assert store.jobs(kind="query_map") == []


def test_global_question_quarantines_public_call_center_number(tmp_path) -> None:
    store = GraphStore(tmp_path / "state")
    source = sources_from_batch(fixture_batch())[0]
    source["payload"]["units"][0]["text"] += " 문의 1644-6621"
    source["payload"]["units"][0]["end"] = len(source["payload"]["units"][0]["text"])
    source["fingerprint"] = fingerprint(source["payload"])
    store.put_sources([source])

    question = submit_question(store, "공식 기록의 주제는?", "global", SIGNATURE)
    status = question_status(store, question["id"])
    assert status["retrieval"]["sensitiveUnitsExcluded"] == 1
    assert store.jobs(kind="query_map") == []


def test_global_question_quarantines_contact_bearing_report_proof(tmp_path) -> None:
    """Community summarization cannot reintroduce an excluded contact value."""
    factory, source = make_factory(tmp_path)
    source["payload"]["units"][0]["text"] += " 사무실 전화 02-123-4567"
    source["payload"]["units"][0]["end"] = len(source["payload"]["units"][0]["text"])
    source["fingerprint"] = fingerprint(source["payload"])
    factory.store.put_sources([source])
    drain(factory)

    question = submit_question(
        factory.store, "김가 의원의 공식 기록은?", "global", SIGNATURE
    )
    status = question_status(factory.store, question["id"])
    assert status["state"] == "insufficient_evidence"
    assert status["retrieval"]["sensitiveCommunityProofsExcluded"] >= 1
    assert status["retrieval"]["sensitiveUnitsExcluded"] == 1


def test_local_question_quarantines_contact_bearing_proof(tmp_path) -> None:
    """The local graph route applies the same source minimization gate."""
    store = GraphStore(tmp_path / "state")
    source = sources_from_batch(fixture_batch())[0]
    source["payload"]["units"][0]["text"] += " 사무실 전화 02-123-4567"
    source["payload"]["units"][0]["end"] = len(source["payload"]["units"][0]["text"])
    source["fingerprint"] = fingerprint(source["payload"])
    store.put_sources([source])

    question = submit_question(store, "김가 의원의 기록은?", "local", SIGNATURE)
    assert question_status(store, question["id"])["state"] == "insufficient_evidence"
    assert store.jobs(kind="query_local") == []
