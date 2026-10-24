"""Request missing office relations from the model with exact source forms."""

import json
import time

import pytest
from test_graphrag_engine import SIGNATURE, RemoteFixture
from test_graphrag_inputs import fixture_batch

from parliament_worker.graphrag.engine import Factory
from parliament_worker.graphrag.index import source_dependency
from parliament_worker.graphrag.inputs import fingerprint, sources_from_batch
from parliament_worker.graphrag.office_repair import (
    OFFICE_CUE,
    plan_office_repairs,
    source_form,
    validate_composite_source_proof,
)
from parliament_worker.graphrag.output_contract import materialize_compact_extraction
from parliament_worker.graphrag.policy import apply_review_policy
from parliament_worker.graphrag.prompts import PROMPT_VERSION, validate_extraction
from parliament_worker.graphrag.source_forms import same_spelling_ignoring_space
from parliament_worker.graphrag.store import GraphStore


def office_source(text: str) -> dict:
    """Build one fixed official-style profile with known source-bound IDs."""
    batch = fixture_batch()
    batch["entities"][0].update(id="p-office", name="고민수")
    batch["entities"][1].update(
        id="o-office", kind="organization", name="방송미디어통신위원회"
    )
    batch["documents"][0]["segments"][0]["text"] = text
    batch["evidence"][0]["end"] = len(text)
    return sources_from_batch(batch)[0]


def indexed_store(tmp_path, text: str) -> GraphStore:
    """Persist a completed ordinary extraction with no office edge."""
    store = GraphStore(tmp_path / "state")
    source = office_source(text)
    store.put_sources([source])
    source = store.sources()[0]
    unit = source["payload"]["units"][0]
    store.put_artifact(
        "graph",
        f"{source['scope']}:{unit['id']}",
        {
            "sources": [source_dependency(source)],
            "model_signature": SIGNATURE,
            "prompt_version": PROMPT_VERSION,
        },
        {"nodes": [], "edges": [], "public": False},
    )
    return store


def test_source_form_only_accepts_unique_horizontal_whitespace_variant():
    assert source_form("고 민 수 부위원장", "고민수") == "고 민 수"
    assert same_spelling_ignoring_space("고\n민수", "고민수") is False
    assert source_form("고 민 자 부위원장", "고민수") is None
    assert source_form("고민수 부위원장", "고민수") == "고민수"
    assert source_form("고\n민수 부위원장", "고민수") is None


def test_office_cue_includes_agency_chief_title():
    assert OFFICE_CUE.search("초대 지식재산처장")


def test_repair_job_asks_model_for_only_evidenced_office_claim(tmp_path):
    store = indexed_store(tmp_path, "고 민 수 부위원장 방송미디어통신위원회")
    assert plan_office_repairs(store, SIGNATURE) == 1
    assert plan_office_repairs(store, SIGNATURE) == 0
    job = store.jobs(kind="extract")[0]
    data = json.loads(job["request"]["messages"][-1]["content"])
    aliases = job["context"]["aliases"]
    person = next(
        alias for alias, value in aliases.items() if value["kind"] == "person"
    )
    org = next(
        alias for alias, value in aliases.items() if value["kind"] == "organization"
    )
    assert data["types"] == ["holds_office"]
    assert (
        next(item["name"] for item in data["known"] if item["id"] == person)
        == "고 민 수"
    )
    assert job["context"]["sourceForms"][person] == "고 민 수"
    assert job["request"]["response_format"]["json_schema"]["schema"]["properties"][
        "relations"
    ]["items"]["properties"]["claim"]["enum"] == [f"holds_office:{person}>{org}"]

    output = {
        "entities": [],
        "relations": [{"claim": f"holds_office:{person}>{org}", "unit": "U1"}],
    }
    grounded = materialize_compact_extraction(output, job["context"])
    result = validate_extraction(grounded, job["context"])
    assert len(result["edges"]) == 1
    assert result["edges"][0]["source"] == "p-office"
    assert result["edges"][0]["target"] == "o-office"
    assert (
        result["edges"][0]["evidence"][0]["text"]
        == "고 민 수 부위원장 방송미디어통신위원회"
    )


def test_repair_rejects_forged_source_form_and_absent_role(tmp_path):
    store = indexed_store(tmp_path, "고 민 수 방송미디어통신위원회")
    assert plan_office_repairs(store, SIGNATURE) == 0

    store = indexed_store(tmp_path / "other", "고 민 수 부위원장 방송미디어통신위원회")
    assert plan_office_repairs(store, SIGNATURE) == 1
    job = store.jobs(kind="extract")[0]
    job["context"]["sourceForms"] = {
        **job["context"]["sourceForms"],
        next(
            alias
            for alias, entity in job["context"]["aliases"].items()
            if entity["kind"] == "person"
        ): "고 민 자",
    }
    aliases = job["context"]["aliases"]
    person = next(
        alias for alias, value in aliases.items() if value["kind"] == "person"
    )
    org = next(
        alias for alias, value in aliases.items() if value["kind"] == "organization"
    )
    output = materialize_compact_extraction(
        {
            "entities": [],
            "relations": [{"claim": f"holds_office:{person}>{org}", "unit": "U1"}],
        },
        job["context"],
    )
    with pytest.raises(ValueError, match="quoted identity"):
        validate_extraction(output, job["context"])


def test_continuous_factory_plans_spaced_office_repair(tmp_path):
    store = indexed_store(tmp_path, "고 민 수 부위원장 방송미디어통신위원회")
    factory = Factory(store, RemoteFixture(), SIGNATURE)
    assert factory.plan()["office_repairs"] == 1
    assert factory.plan()["office_repairs"] == 0


def test_typed_tenure_repairs_exact_office_name_but_excludes_untyped_pair(tmp_path):
    text = "고민수 부위원장 방송미디어통신위원회"
    store = indexed_store(tmp_path, text)
    assert plan_office_repairs(store, SIGNATURE, typed_pairs=set()) == 0
    assert (
        plan_office_repairs(store, SIGNATURE, typed_pairs={("p-office", "o-office")})
        == 1
    )
    job = store.jobs(kind="extract")[0]
    assert job["context"]["aliases"]
    assert job["context"]["repair_version"]
    assert (
        plan_office_repairs(store, SIGNATURE, typed_pairs={("p-office", "o-office")})
        == 0
    )


def test_typed_officeholder_list_row_uses_its_source_category(tmp_path):
    source = office_source("경기도 파주시 고민수")
    next(
        entity
        for entity in source["payload"]["entities"]
        if entity["kind"] == "organization"
    )["name"] = "경기도 파주시"
    source["payload"]["document"].update(
        sourceKey="roster_NAMK_OFFICEHOLDER_SNAPSHOT",
        title="고민수 · 기초단체장 명부 표기 명부 근거",
    )
    source["fingerprint"] = fingerprint(source["payload"])
    store = GraphStore(tmp_path / "state")
    store.put_sources([source])
    unit = source["payload"]["units"][0]
    store.put_artifact(
        "graph",
        f"{source['scope']}:{unit['id']}",
        {
            "sources": [source_dependency(store.sources()[0])],
            "model_signature": SIGNATURE,
            "prompt_version": PROMPT_VERSION,
        },
        {"nodes": [], "edges": [], "public": False},
    )

    assert plan_office_repairs(store, SIGNATURE, typed_pairs=set()) == 0
    assert (
        plan_office_repairs(store, SIGNATURE, typed_pairs={("p-office", "o-office")})
        == 1
    )
    job = store.jobs(kind="extract")[0]
    prompt = json.loads(job["request"]["messages"][-1]["content"])
    assert prompt["document"]["title"] == "고민수 · 기초단체장 명부 표기 명부 근거"
    assert prompt["types"] == ["holds_office"]
    assert job["context"]["repair_version"] == "source-typed-list-office-v1"
    assert (
        job["context"]["units"]["U1"]["sourceTitle"]
        == "고민수 · 기초단체장 명부 표기 명부 근거"
    )
    aliases = job["context"]["aliases"]
    person = next(key for key, value in aliases.items() if value["kind"] == "person")
    organization = next(
        key for key, value in aliases.items() if value["kind"] == "organization"
    )
    output = materialize_compact_extraction(
        {
            "entities": [],
            "relations": [
                {"claim": f"holds_office:{person}>{organization}", "unit": "U1"}
            ],
        },
        job["context"],
    )
    graph = apply_review_policy(validate_extraction(output, job["context"]))
    assert graph["edges"][0]["decision"] == "pending"
    assert (
        graph["edges"][0]["evidence"][0]["sourceTitle"]
        == "고민수 · 기초단체장 명부 표기 명부 근거"
    )
    assert (
        plan_office_repairs(store, SIGNATURE, typed_pairs={("p-office", "o-office")})
        == 0
    )


def test_typed_list_completion_rechecks_official_title(tmp_path):
    source = office_source("경기도 파주시 고민수")
    next(
        entity
        for entity in source["payload"]["entities"]
        if entity["kind"] == "organization"
    )["name"] = "경기도 파주시"
    source["payload"]["document"].update(
        sourceKey="roster_NAMK_OFFICEHOLDER_SNAPSHOT",
        title="고민수 · 기초단체장 명부 표기 명부 근거",
    )
    source["fingerprint"] = fingerprint(source["payload"])
    store = GraphStore(tmp_path / "state")
    store.put_sources([source])
    unit = source["payload"]["units"][0]
    store.put_artifact(
        "graph",
        f"{source['scope']}:{unit['id']}",
        {
            "sources": [source_dependency(store.sources()[0])],
            "model_signature": SIGNATURE,
            "prompt_version": PROMPT_VERSION,
        },
        {"nodes": [], "edges": [], "public": False},
    )
    assert (
        plan_office_repairs(store, SIGNATURE, typed_pairs={("p-office", "o-office")})
        == 1
    )
    factory = Factory(store, RemoteFixture(), SIGNATURE)
    job_id = store.jobs(kind="extract")[0]["id"]
    store.update_job(job_id, state="submitting")
    job = store.claim(factory.owner, 60)[0]
    job["context"]["units"]["U1"]["sourceTitle"] = "다른 명부"
    response = {
        "_modelMetadata": {"actual_model": "test-model", "revision": "test-revision"},
        "result": {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": json.dumps({"entities": [], "relations": []})
                    },
                }
            ]
        },
    }

    with pytest.raises(ValueError, match="list source proof"):
        factory._complete(job, response, time.time())

    assert store.get_artifact("graph", job["context"]["artifact_key"]) is None


def test_typed_office_relation_split_across_adjacent_units_is_queued(tmp_path):
    text = "가" * 281 + "방송미디어통신위원회 부위원장 고민수"
    store = indexed_store(tmp_path, text)
    source = store.sources()[0]
    assert len(source["payload"]["units"]) == 2
    for unit in source["payload"]["units"][1:]:
        store.put_artifact(
            "graph",
            f"{source['scope']}:{unit['id']}",
            {
                "sources": [source_dependency(source)],
                "model_signature": SIGNATURE,
                "prompt_version": PROMPT_VERSION,
            },
            {"nodes": [], "edges": [], "public": False},
        )

    assert (
        plan_office_repairs(store, SIGNATURE, typed_pairs={("p-office", "o-office")})
        == 1
    )
    job = store.jobs(kind="extract")[0]
    validate_composite_source_proof(job["context"], source)
    assert job["context"]["repair_version"] == "source-cross-unit-office-v1"
    combined = job["context"]["units"]["U1"]
    assert len(combined["sourceUnitIds"]) == 2
    assert "방송미디어통신위원회 부위원장 고민수" in combined["text"]
    assert len(combined["text"].encode()) <= 850
    original = "".join(unit["text"] for unit in source["payload"]["units"])
    assert (
        combined["text"]
        == original[
            combined["start"]
            - source["payload"]["units"][0]["start"] : combined["end"]
            - source["payload"]["units"][0]["start"]
        ]
    )
    aliases = job["context"]["aliases"]
    person = next(
        alias for alias, value in aliases.items() if value["kind"] == "person"
    )
    organization = next(
        alias for alias, value in aliases.items() if value["kind"] == "organization"
    )
    output = materialize_compact_extraction(
        {
            "entities": [],
            "relations": [
                {"claim": f"holds_office:{person}>{organization}", "unit": "U1"}
            ],
        },
        job["context"],
    )
    graph = validate_extraction(output, job["context"])
    assert (
        graph["edges"][0]["evidence"][0]["sourceUnitIds"] == combined["sourceUnitIds"]
    )
    assert (
        plan_office_repairs(store, SIGNATURE, typed_pairs={("p-office", "o-office")})
        == 0
    )


def test_cross_unit_completion_checks_immutable_source_text(tmp_path):
    text = "가" * 281 + "방송미디어통신위원회 부위원장 고민수"
    store = indexed_store(tmp_path, text)
    source = store.sources()[0]
    for unit in source["payload"]["units"][1:]:
        store.put_artifact(
            "graph",
            f"{source['scope']}:{unit['id']}",
            {
                "sources": [source_dependency(source)],
                "model_signature": SIGNATURE,
                "prompt_version": PROMPT_VERSION,
            },
            {"nodes": [], "edges": [], "public": False},
        )
    assert (
        plan_office_repairs(store, SIGNATURE, typed_pairs={("p-office", "o-office")})
        == 1
    )
    factory = Factory(store, RemoteFixture(), SIGNATURE)
    job_id = store.jobs(kind="extract")[0]["id"]
    store.update_job(job_id, state="submitting")
    store.update_job(job_id, state="polling", remote_id="test-request")
    job = store.claim(factory.owner, 60, now=time.time())[0]
    combined = job["context"]["units"]["U1"]
    combined["text"] = combined["text"].replace("가", "나", 1)
    aliases = job["context"]["aliases"]
    person = next(
        alias for alias, value in aliases.items() if value["kind"] == "person"
    )
    organization = next(
        alias for alias, value in aliases.items() if value["kind"] == "organization"
    )
    response = {
        "_modelMetadata": {"actual_model": "test-model", "revision": "test-revision"},
        "result": {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": json.dumps(
                            {
                                "entities": [],
                                "relations": [
                                    {
                                        "claim": f"holds_office:{person}>{organization}",
                                        "unit": "U1",
                                    }
                                ],
                            },
                            ensure_ascii=False,
                        )
                    },
                }
            ]
        },
    }
    with pytest.raises(ValueError, match="composite source proof"):
        factory._complete(job, response, time.time())
    assert store.get_artifact("graph", job["context"]["artifact_key"]) is None


def test_factory_loads_typed_tenures_without_changing_graph_source(tmp_path):
    batch = fixture_batch()
    batch["entities"][0].update(id="p-office", name="고민수")
    batch["entities"][1].update(
        id="o-office", kind="organization", name="방송미디어통신위원회"
    )
    batch["entities"][0]["tenures"] = [
        {"organizationId": "o-office", "position": "부위원장", "evidenceIds": ["ev-a"]}
    ]
    text = "고민수 부위원장 방송미디어통신위원회"
    batch["documents"][0]["segments"][0]["text"] = text
    batch["evidence"][0]["end"] = len(text)
    path = tmp_path / "batch.json"
    path.write_text(json.dumps(batch, ensure_ascii=False))
    store = GraphStore(tmp_path / "state")
    store.put_sources(sources_from_batch(batch))
    source = store.sources()[0]
    unit = source["payload"]["units"][0]
    store.put_artifact(
        "graph",
        f"{source['scope']}:{unit['id']}",
        {
            "sources": [source_dependency(source)],
            "model_signature": SIGNATURE,
            "prompt_version": PROMPT_VERSION,
        },
        {"nodes": [], "edges": [], "public": False},
    )
    factory = Factory(store, RemoteFixture(), SIGNATURE)
    assert factory.sync_inputs([path])["changed"] == 0
    assert factory.plan()["office_repairs"] == 1
    assert store.jobs(kind="extract")[0]["context"]["repair_version"] == (
        "source-typed-office-v1"
    )
