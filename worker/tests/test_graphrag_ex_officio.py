"""Two official revisions must jointly support a private chair candidate."""

import time
from copy import deepcopy

import pytest
from fixtures_ex_officio import chair_batch
from test_graphrag_engine import SIGNATURE
from test_graphrag_lineage_repair import completed_reply

from parliament_worker.graphrag.engine import Factory
from parliament_worker.graphrag.ex_officio import (
    plan_ex_officio_links,
    validate_ex_officio_link,
)
from parliament_worker.graphrag.inputs import sources_from_batch
from parliament_worker.graphrag.output_retries import _next_request, _retry_contract
from parliament_worker.graphrag.provenance_audit import audit_provenance
from parliament_worker.graphrag.store import GraphStore


def test_curated_batch_retains_three_selected_official_sources() -> None:
    """No source can borrow the other source's identity or evidence span."""
    sources = sources_from_batch(chair_batch())

    assert {source["scope"] for source in sources} == {
        "official-president-status:briefing-XvTXtZbh",
        "official-exofficio-rule:neac-chair",
        "official-exofficio-rule:pacst-chair",
    }
    assert all(source["payload"]["public"] is False for source in sources)
    assert all(
        source["payload"]["bodyCoverage"] == "selected_evidence" for source in sources
    )
    assert all(len(source["payload"]["units"]) == 1 for source in sources)
    by_scope = {source["scope"]: source for source in sources}
    president = by_scope["official-president-status:briefing-XvTXtZbh"]
    assert {item["id"] for item in president["payload"]["entities"]} == {
        "person-president-fixture"
    }
    assert "합성인 대통령" in president["payload"]["units"][0]["text"]
    assert (
        "대통령(의장)"
        in by_scope["official-exofficio-rule:neac-chair"]["payload"]["units"][0]["text"]
    )
    neac = by_scope["official-exofficio-rule:neac-chair"]["payload"]
    assert "국민경제자문회의" in neac["document"]["title"]
    assert [
        (item["name"], item["identifiers"])
        for item in neac["entities"]
        if item["kind"] == "organization"
    ] == [
        (
            "국민경제자문회의",
            [{"namespace": "MOIS_GOVERNMENT_ORGANIZATION", "value": "1790049"}],
        )
    ]
    assert (
        "대통령(의장)"
        in by_scope["official-exofficio-rule:pacst-chair"]["payload"]["units"][0][
            "text"
        ]
    )


def _prepared(tmp_path):
    store = GraphStore(tmp_path / "state")
    store.put_sources(sources_from_batch(chair_batch()))
    sources = {source["scope"]: source for source in store.sources()}
    return store, sources


def test_two_committees_enqueue_distinct_two_source_decisions(tmp_path) -> None:
    store, sources = _prepared(tmp_path)

    assert plan_ex_officio_links(store, SIGNATURE, 10) == 2
    jobs = [
        job
        for job in store.jobs(kind="extract")
        if job["context"].get("relation_task") == "ex_officio_chair"
    ]
    assert len(jobs) == 2
    assert len({job["key"] for job in jobs}) == 2
    assert len({job["idempotency_key"] for job in jobs}) == 2
    assert plan_ex_officio_links(store, SIGNATURE, 10) == 0
    for job in jobs:
        context = job["context"]
        assert len(context["sources"]) == 2
        assert (
            context["sources"][0]["scope"]
            == "official-president-status:briefing-XvTXtZbh"
        )
        assert context["sources"][1]["scope"].startswith("official-exofficio-rule:")
        assert (
            context["units"]["P"]
            == sources[context["sources"][0]["scope"]]["payload"]["units"][0]
        )
        assert (
            context["units"]["R"]
            == sources[context["sources"][1]["scope"]]["payload"]["units"][0]
        )
        assert job["request"]["response_format"]["json_schema"]["schema"][
            "properties"
        ] == {"supported": {"type": "boolean"}}
        assert job["request"]["max_completion_tokens"] <= 128


def test_puac_rule_uses_existing_president_and_exact_official_organization(
    tmp_path,
) -> None:
    store, sources = _prepared(tmp_path)
    puac = sources_from_batch(chair_batch(extra_rule="puac-chair"))
    assert len(puac) == 1
    store.put_sources(puac)
    sources = {source["scope"]: source for source in store.sources()}

    assert plan_ex_officio_links(store, SIGNATURE, 10) == 3
    job = next(
        item
        for item in store.jobs(kind="extract")
        if item["context"].get("relation_task") == "ex_officio_chair"
        and item["context"]["sources"][1]["scope"]
        == "official-exofficio-rule:puac-chair"
    )
    context = job["context"]
    assert context["organizationId"] == ("org-fixture-puac-chair")
    selected = [sources[dependency["scope"]] for dependency in context["sources"]]
    graph = validate_ex_officio_link({"supported": True}, context, selected)
    assert graph["public"] is False
    assert graph["edges"][0]["decision"] == "pending"
    assert [item["text"] for item in graph["edges"][0]["evidence"]] == [
        context["units"]["P"]["text"],
        "[ 의장 : 대통령 ]",
    ]


def test_nsc_law_clause_requires_exact_chair_statement_and_stable_org_id(
    tmp_path,
) -> None:
    store, _ = _prepared(tmp_path)
    nsc = sources_from_batch(chair_batch(extra_rule="nsc-chair"))
    assert len(nsc) == 1
    store.put_sources(nsc)

    assert plan_ex_officio_links(store, SIGNATURE, 10) == 3
    job = next(
        item
        for item in store.jobs(kind="extract")
        if item["context"].get("relation_task") == "ex_officio_chair"
        and item["context"]["sources"][1]["scope"]
        == "official-exofficio-rule:nsc-chair"
    )
    assert job["context"]["organizationId"] == ("org-fixture-nsc-chair")
    sources = {source["scope"]: source for source in store.sources()}
    selected = [
        sources[dependency["scope"]] for dependency in job["context"]["sources"]
    ]
    graph = validate_ex_officio_link({"supported": True}, job["context"], selected)
    assert graph["public"] is False
    assert graph["edges"][0]["decision"] == "pending"
    assert graph["edges"][0]["evidence"][1]["text"] == (
        "② 대통령은 회의의 의장이 된다."
    )


def test_two_source_result_is_private_with_both_fixed_proofs(tmp_path) -> None:
    store, sources = _prepared(tmp_path)
    assert plan_ex_officio_links(store, SIGNATURE, 10) == 2
    job = next(
        job
        for job in store.jobs(kind="extract")
        if job["context"].get("relation_task") == "ex_officio_chair"
    )
    context = job["context"]
    selected = [sources[dependency["scope"]] for dependency in context["sources"]]

    graph = validate_ex_officio_link({"supported": True}, context, selected)

    assert graph["public"] is False
    assert len(graph["edges"]) == 1
    edge = graph["edges"][0]
    assert edge["type"] == "holds_office"
    assert edge["decision"] == "pending"
    assert edge["evidence"] == [context["units"]["P"], context["units"]["R"]]
    assert {node["kind"] for node in graph["nodes"]} == {"person", "organization"}
    assert (
        validate_ex_officio_link({"supported": False}, context, selected)["edges"] == []
    )

    for bad in ({"supported": "true"}, {"supported": True, "reason": "yes"}):
        with pytest.raises(ValueError):
            validate_ex_officio_link(bad, context, selected)
    tampered = deepcopy(context)
    tampered["units"]["R"]["text"] += " 조작"
    with pytest.raises(ValueError):
        validate_ex_officio_link({"supported": True}, tampered, selected)
    tampered = deepcopy(context)
    tampered["personId"] = "other-person"
    with pytest.raises(ValueError):
        validate_ex_officio_link({"supported": True}, tampered, selected)


def test_source_revision_changes_logical_work_without_mutating_prior_request(
    tmp_path,
) -> None:
    store, sources = _prepared(tmp_path)
    assert plan_ex_officio_links(store, SIGNATURE, 10) == 2
    before = {job["key"]: job for job in store.jobs(kind="extract")}
    scope = "official-exofficio-rule:neac-chair"
    changed = deepcopy(sources[scope]["payload"])
    changed["units"][0]["text"] += " 개정"
    changed["units"][0]["end"] += len(" 개정")
    store.put_source(scope, "changed-rule-v2", changed)

    assert plan_ex_officio_links(store, SIGNATURE, 10) == 1
    after = [job for job in store.jobs(kind="extract") if job["key"] not in before]
    assert len(after) == 1
    assert after[0]["context"]["sources"][1]["scope"] == scope
    assert all(
        before[key]["request"] == store.get_job(before[key]["id"])["request"]
        for key in before
    )


def test_retry_preserves_two_source_boolean_contract(tmp_path) -> None:
    store, _ = _prepared(tmp_path)
    plan_ex_officio_links(store, SIGNATURE, 10)
    job = next(
        job
        for job in store.jobs(kind="extract")
        if job["context"].get("relation_task") == "ex_officio_chair"
    )

    assert _retry_contract(job, 2) == job["context"]["output_contract"]
    assert _next_request(job, 2)["response_format"] == job["request"]["response_format"]


def test_factory_projects_pending_two_source_edge_and_audits_both_proofs(
    tmp_path,
) -> None:
    store, _ = _prepared(tmp_path)
    factory = Factory(store, None, SIGNATURE)
    factory.plan()
    claimed = store.claim(factory.owner, lease_seconds=600, limit=20)
    job = next(
        item
        for item in claimed
        if item["context"].get("relation_task") == "ex_officio_chair"
    )
    job = store.checkpoint(job["id"], factory.owner, state="submitting")

    factory._complete(job, completed_reply(True), time.time())

    graph = store.get_artifact("graph", job["context"]["artifact_key"])
    assert graph is not None
    edge = graph["payload"]["edges"][0]
    assert graph["payload"]["public"] is False
    assert edge["decision"] == "pending"
    assert edge["publicationBlockedBy"]
    assert len(edge["evidence"]) == 2
    report = audit_provenance(
        {
            "sources": store.sources(),
            "model": store.get_artifact("control", "model"),
            "artifacts": {"graph": store.artifacts("graph"), "community": []},
        }
    )
    assert report["findings"].get("edgeProofNotInSource", 0) == 0
