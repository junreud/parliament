"""Adversarial review regressions for grounded links and incremental communities."""

from copy import deepcopy

import pytest
from test_graphrag_engine import SIGNATURE, drain, make_factory
from test_graphrag_inputs import fixture_batch
from test_graphrag_validation import extracted

from parliament_worker.graphrag.engine import Factory
from parliament_worker.graphrag.index import (
    current_artifacts,
    reconcile,
)
from parliament_worker.graphrag.inputs import fingerprint, sources_from_batch
from parliament_worker.graphrag.prompts import validate_extraction, validate_report
from parliament_worker.graphrag.query import validate_answer
from parliament_worker.graphrag.reduction import paired_context


@pytest.mark.parametrize(
    "body",
    [
        {"entities": [None], "relations": []},
        {"entities": [{"id": []}], "relations": []},
        {"entities": [], "relations": [None]},
        {"entities": [], "relations": [{"s": [], "t": "E1", "type": "concerns"}]},
    ],
)
def test_malformed_extraction_is_a_validation_error(body):
    _, context = extracted()
    with pytest.raises(ValueError):
        validate_extraction(body, context)


@pytest.mark.parametrize("groups", [[None], [{"members": [[]], "claims": []}]])
def test_malformed_community_is_a_validation_error(groups):
    with pytest.raises(ValueError):
        validate_report(
            {"groups": groups},
            {"aliases": {"E1": {"id": "p"}}, "units": {}, "level": 0},
        )


def test_malformed_answer_quote_alias_is_a_validation_error():
    with pytest.raises(ValueError):
        validate_answer(
            {
                "claims": [{"text": "fact", "unit": [], "quote": "text"}],
                "insufficient": False,
            },
            {"units": {}},
        )


def test_invalid_model_shapes_fail_one_job_and_keep_factory_running(tmp_path):
    import json

    factory, _ = make_factory(tmp_path)
    factory.plan()
    factory.tick(1)
    job = factory.store.jobs()[0]
    factory.store.update_job(job["id"], next_poll=0)
    original = factory.client.poll

    def malformed(key):
        reply = original(key)
        reply["result"]["choices"][0]["message"]["content"] = json.dumps(
            {"entities": [], "relations": [{"s": [], "t": "E1", "type": "concerns"}]}
        )
        return reply

    factory.client.poll = malformed
    factory.tick(1)
    assert factory.store.get_job(job["id"])["state"] == "failed"
    assert factory.store.get_artifact("failure", job["id"]) is not None
    assert factory.tick(1) == 0


def test_unrelated_quote_cannot_create_or_approve_general_relationship():
    _, context = extracted()
    context["aliases"] = {
        "E1": {
            "id": "policy",
            "name": "관련 없는 정책",
            "kind": "policy",
            "identifiers": [],
        },
        "E2": {"id": "bill", "name": "다른 법안", "kind": "bill", "identifiers": []},
    }
    with pytest.raises(ValueError):
        validate_extraction(
            {
                "entities": [],
                "relations": [
                    {
                        "s": "E1",
                        "t": "E2",
                        "type": "concerns",
                        "unit": "U1",
                        "quote": "대표발의했다.",
                    }
                ],
            },
            context,
        )


def test_report_freeform_accusation_is_discarded_in_favor_of_cited_claims():
    output, context = extracted()
    from parliament_worker.graphrag.prompts import community_task

    graph = validate_extraction(output, context)
    _, context = community_task(graph["nodes"], graph["edges"][0]["evidence"], level=0)
    report = validate_report(
        {
            "groups": [
                {
                    "title": "법안",
                    "members": list(context["aliases"]),
                    "summary": "근거에 없는 범죄 주장",
                    "claims": [
                        {
                            "text": "대표발의 기록",
                            "unit": "S1",
                            "quote": "대표발의했다.",
                        }
                    ],
                }
            ]
        },
        context,
    )
    assert report["groups"][0]["summary"] == "대표발의 기록"


def test_model_revision_a_b_a_restores_matching_cached_projection(tmp_path):
    factory, _ = make_factory(tmp_path)
    drain(factory)
    original = current_artifacts(factory.store, "graph")[0]["version"]
    factory.client.model["revision"] = "revision-b"
    changed = Factory(
        factory.store, factory.client, "test-model@revision-b", poll_seconds=0.1
    )
    drain(changed)
    assert (
        current_artifacts(factory.store, "graph")[0]["dependency"]["model_signature"]
        == "test-model@revision-b"
    )
    factory.client.model["revision"] = "test-revision"
    restored = Factory(factory.store, factory.client, SIGNATURE, poll_seconds=0.1)
    drain(restored)
    assert current_artifacts(factory.store, "graph")[0]["version"] == original
    assert all(
        artifact["dependency"]["model_signature"] == SIGNATURE
        for artifact in current_artifacts(factory.store, "community")
    )


def test_correcting_one_of_nine_sources_preserves_unaffected_parent_versions(tmp_path):
    factory, _ = make_factory(tmp_path)
    factory.store.retire_source("assembly:2")
    sources = []
    for number in range(9):
        batch = fixture_batch()
        batch["documents"][0]["recordKey"] = str(number)
        batch["entities"][0]["id"] = f"p-{number}"
        batch["entities"][1]["id"] = f"b-{number // 3}"
        sources.append(sources_from_batch(batch)[0])
    factory.store.put_sources(sources)
    drain(factory, cycles=80)
    before = current_artifacts(factory.store, "community")
    parents = [item for item in before if item["payload"]["level"] > 0]
    assert parents
    target = "assembly:8"
    unaffected = {
        item["key"]: item["version"]
        for item in parents
        if all(d["scope"] != target for d in item["dependency"]["sources"])
    }
    changed = deepcopy(next(source for source in sources if source["scope"] == target))
    changed["payload"]["document"]["version"] = "version-b"
    changed["payload"]["units"][0]["documentVersion"] = "version-b"
    changed["fingerprint"] = fingerprint(changed["payload"])
    factory.store.put_sources([changed])
    reconcile(factory.store)
    drain(factory, cycles=80)
    after = current_artifacts(factory.store, "community")
    assert len([item for item in after if item["payload"]["level"] == 0]) == 9
    assert {
        item["key"]: item["version"] for item in after if item["key"] in unaffected
    } == unaffected
    assert max(item["payload"]["level"] for item in after) == max(
        item["payload"]["level"] for item in before
    )


def test_multiple_claims_sharing_proof_do_not_shift_another_claim_citation():
    p1, p2 = {"text": "A", "id": "a"}, {"text": "B", "id": "b"}
    proofs, summaries = paired_context(
        [
            {"text": "A1", "evidence": p1},
            {"text": "A2", "evidence": p1},
            {"text": "B1", "evidence": p2},
        ]
    )
    assert proofs == [p1, p2]
    assert summaries == [
        {"summary": "A1", "unit": "S1"},
        {"summary": "A2", "unit": "S1"},
        {"summary": "B1", "unit": "S2"},
    ]


def test_same_name_new_candidates_in_different_segments_remain_distinct():
    _, context = extracted()
    unit = context["units"]["U1"]
    candidate = {
        "entities": [
            {
                "id": "N1",
                "name": "김영수",
                "kind": "person",
                "unit": "U1",
                "quote": "김영수",
            }
        ],
        "relations": [],
    }
    first = {
        **context,
        "aliases": {},
        "units": {
            "U1": {
                **unit,
                "segmentId": "seg-a",
                "text": "김영수 의원에 관한 기록",
                "start": 0,
            }
        },
    }
    second = {
        **context,
        "aliases": {},
        "units": {
            "U1": {
                **unit,
                "segmentId": "seg-b",
                "text": "김영수 장관에 관한 기록",
                "start": 0,
            }
        },
    }
    a = validate_extraction(candidate, first)["nodes"][0]["id"]
    b = validate_extraction(candidate, second)["nodes"][0]["id"]
    assert a != b


def test_local_retrieval_does_not_walk_a_whole_chain_in_one_hop(tmp_path):
    from parliament_worker.graphrag.query import _local_context

    factory, _ = make_factory(tmp_path)
    source = factory.store.sources()[0]
    proof = source["payload"]["units"][0]
    nodes = [
        {
            "id": f"n-{i}",
            "kind": "person",
            "name": "Anchor" if i == 0 else f"Unrelated{i}",
        }
        for i in range(12)
    ]
    edges = [
        {
            "id": f"edge-{i}",
            "source": f"n-{i}",
            "target": f"n-{i+1}",
            "type": "concerns",
            "decision": "pending",
            "evidence": [proof],
        }
        for i in range(11)
    ]
    factory.store.put_artifact(
        "graph",
        "chain",
        {"sources": [{k: source[k] for k in ("scope", "fingerprint", "generation")}]},
        {"nodes": nodes, "edges": edges},
    )
    _, context, retrieval = _local_context(factory.store, "Anchor")
    assert retrieval["neighborEntities"] == 3
    assert retrieval["graphEdges"] == 2


def test_local_retrieval_prefers_an_evidenced_role_over_loose_text_match(tmp_path):
    from copy import deepcopy

    from parliament_worker.graphrag.query import _local_context

    factory, source = make_factory(tmp_path)
    changed = deepcopy(source)
    role_proof = changed["payload"]["units"][0]
    loose = {**role_proof, "id": "loose-text", "text": "김가 대표발의 대표발의"}
    changed["payload"]["units"].append(loose)
    changed["fingerprint"] = fingerprint(changed["payload"])
    factory.store.put_sources([changed])
    stored = factory.store.sources()[0]
    factory.store.put_artifact(
        "graph",
        "role-proof",
        {
            "sources": [
                {key: stored[key] for key in ("scope", "fingerprint", "generation")}
            ]
        },
        {
            "nodes": [
                {"id": "p-a", "kind": "person", "name": "김가"},
                {"id": "b-a", "kind": "bill", "name": "법안"},
            ],
            "edges": [
                {
                    "id": "sponsor-proof",
                    "source": "p-a",
                    "target": "b-a",
                    "type": "lead_sponsor",
                    "decision": "pending",
                    "evidence": [role_proof],
                }
            ],
        },
    )
    selected, _, _ = _local_context(factory.store, "김가의 대표발의는?")
    assert selected[0]["id"] == role_proof["id"]


def test_local_retrieval_keeps_an_answerable_passage_ahead_of_short_labels(tmp_path):
    from parliament_worker.graphrag.query import _local_context

    factory, source = make_factory(tmp_path)
    changed = deepcopy(source)
    substantive = (
        "성평등가족부는 양육비 채무 불이행자에 대한 제재조치와 "
        "양육비 선지급금 회수 방안을 논의하는 전문가 간담회를 개최한다고 발표했다."
    )
    labels = [
        "양육비 채무 불이행자",
        "양육비 제재조치",
        "양육비 보도자료",
        "2026년 8월 보도자료",
        "양육비 정부 발표",
        "채무 불이행자 정부",
        "제재조치 발표",
        "공화당 | 2020-03-24 | 김재원",
    ]
    template = changed["payload"]["units"][0]
    changed["payload"]["units"] = [
        {**template, "id": f"label-{index}", "text": text}
        for index, text in enumerate(labels)
    ] + [{**template, "id": "answerable", "text": substantive}]
    changed["fingerprint"] = fingerprint(changed["payload"])
    factory.store.put_sources([changed])

    question = "2026년 8월 양육비 채무 불이행자 보도자료는 무엇을 발표했나요?"
    selected, _, _ = _local_context(factory.store, question)
    assert "answerable" in {proof["id"] for proof in selected}
    assert "label-7" not in {proof["id"] for proof in selected}


def test_different_years_do_not_match_only_on_a_numeric_prefix():
    from parliament_worker.graphrag.query_terms import score

    assert score("2026년", "2020-03-24") == 0


def test_local_retrieval_respects_an_explicit_bill_number(tmp_path):
    from parliament_worker.graphrag.query import _local_context

    factory, source = make_factory(tmp_path)
    changed = deepcopy(source)
    template = changed["payload"]["units"][0]
    generic = "양육비 선지급제와 관련된 정부 발표와 지원 절차를 안내한다."
    changed["payload"]["units"] = [
        {
            **template,
            "id": f"generic-{index}",
            "documentId": "doc-program-guide",
            "text": generic + f" 자료 {index}.",
        }
        for index in range(7)
    ] + [
        {
            **template,
            "id": "target-bill",
            "documentId": "doc-bill-2204313",
            "text": "위원회 대안은 양육비 선지급 제도 도입을 제안한다.",
        }
    ]
    changed["fingerprint"] = fingerprint(changed["payload"])
    factory.store.put_sources([changed])

    selected, _, _ = _local_context(
        factory.store, "법안 2204313은 양육비 선지급제에 관해 무엇을 제안했나요?"
    )
    assert selected[0]["id"] == "target-bill"


def test_person_scoped_retrieval_excludes_same_name_other_person(tmp_path):
    from copy import deepcopy

    from parliament_worker.graphrag.query import _local_context, submit_question

    factory, source = make_factory(tmp_path)
    drain(factory)
    other = deepcopy(source)
    other["scope"] = "assembly:other-person"
    next(
        entity for entity in other["payload"]["entities"] if entity["kind"] == "person"
    )["id"] = "p-other"
    other["payload"]["units"][0]["id"] = "other-unit"
    other["payload"]["units"][0]["text"] = "김가 의원은 다른 법안을 발의했다."
    other["fingerprint"] = fingerprint(other["payload"])
    factory.store.put_sources([other])
    stored = next(s for s in factory.store.sources() if s["scope"] == other["scope"])
    factory.store.put_artifact(
        "graph",
        "other-person",
        {
            "sources": [
                {key: stored[key] for key in ("scope", "fingerprint", "generation")}
            ]
        },
        {
            "nodes": [{"id": "p-other", "kind": "person", "name": "김가"}],
            "edges": [],
        },
    )
    question = "김가는 무엇을 발의했나?"
    selected, _, retrieval = _local_context(factory.store, question, entity_id="p-a")
    assert retrieval["scopedEntity"] == "p-a"
    assert all(
        proof["text"] != "김가 의원은 다른 법안을 발의했다." for proof in selected
    )
    scoped = submit_question(
        factory.store, question, "local", SIGNATURE, entity_id="p-a"
    )
    unscoped = submit_question(factory.store, question, "local", SIGNATURE)
    assert scoped["id"] != unscoped["id"]
    with pytest.raises(ValueError):
        submit_question(factory.store, question, "global", SIGNATURE, entity_id="p-a")
    with pytest.raises(ValueError):
        submit_question(
            factory.store, question, "local", SIGNATURE, entity_id="missing"
        )


def test_identical_answer_sentence_keeps_both_citations_but_renders_once(tmp_path):
    factory, _ = make_factory(tmp_path)
    first = factory.store.sources()[0]["payload"]["units"][0]
    second = {**first, "id": "second-proof", "text": first["text"] + " 추가 기록"}
    sentence = "김가 의원은 법안을 발의했다."
    result = validate_answer(
        {
            "claims": [
                {"text": sentence, "unit": "S1", "quote": first["text"]},
                {"text": sentence, "unit": "S2", "quote": second["text"]},
            ],
            "insufficient": False,
        },
        {"units": {"S1": first, "S2": second}},
    )
    assert result["answer"] == sentence
    assert len(result["claims"]) == 2
