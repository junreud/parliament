"""Bounded parent candidates preserve source-bound entity overlap."""

from test_graphrag_engine import drain, make_factory
from test_graphrag_inputs import fixture_batch

from parliament_worker.graphrag.community_routing import report_anchors
from parliament_worker.graphrag.index import (
    _bounded_groups,
    current_artifacts,
    reconcile,
)
from parliament_worker.graphrag.inputs import sources_from_batch


def test_parent_candidates_follow_shared_entities_before_unrelated_keys():
    def leaf(key: str, person: str, organization: str) -> dict:
        return {
            "key": key,
            "payload": {
                "level": 0,
                "groups": [
                    {
                        "id": f"community-{key}",
                        "title": key,
                        "summary": "",
                        "members": [person, organization],
                        "claims": [],
                    }
                ],
            },
        }

    leaves = [
        leaf("a1", "person-a", "organization-a"),
        leaf("b1", "person-b", "organization-b"),
        leaf("a2", "person-c", "organization-a"),
        leaf("b2", "person-d", "organization-b"),
    ]
    groups = _bounded_groups(leaves, level=1)
    assert [{item["key"] for item in group} for group in groups] == [
        {"a1", "a2"},
        {"b1", "b2"},
    ]


def test_parent_candidates_do_not_force_unrelated_reports_together():
    reports = [
        {
            "key": key,
            "payload": {
                "level": 0,
                "groups": [
                    {
                        "id": key,
                        "title": key,
                        "summary": "",
                        "members": [person],
                        "claims": [],
                    }
                ],
            },
        }
        for key, person in (("a", "person-a"), ("b", "person-b"))
    ]
    assert [
        [item["key"] for item in group] for group in _bounded_groups(reports, 1)
    ] == [
        ["a"],
        ["b"],
    ]


def test_high_degree_hub_alone_does_not_create_arbitrary_communities():
    reports = [
        {
            "key": f"leaf-{number:02d}",
            "payload": {
                "level": 0,
                "groups": [
                    {
                        "id": f"community-{number}",
                        "title": f"Report {number}",
                        "summary": "",
                        "members": [f"person-{number}", "organization-hub"],
                        "claims": [],
                    }
                ],
            },
        }
        for number in range(51)
    ]
    assert all(len(group) == 1 for group in _bounded_groups(reports, 1))


def test_unrelated_growth_does_not_reroute_existing_anchor():
    def report(key: str, members: list[str]) -> dict:
        return {
            "key": key,
            "payload": {
                "level": 0,
                "groups": [
                    {
                        "id": key,
                        "title": key,
                        "summary": "",
                        "members": members,
                        "claims": [],
                    }
                ],
            },
        }

    shared = [
        report(f"h-{number:02d}", [f"person-{number}", "organization-shared"])
        for number in range(12)
    ]
    unrelated = [
        report(f"z-{number:04d}", [f"person-z-{number}"]) for number in range(1187)
    ]

    def shared_groups(items: list[dict]) -> list[set[str]]:
        return [
            {item["key"] for item in group}
            for group in _bounded_groups(items, 1)
            if group[0]["key"].startswith("h-")
        ]

    assert shared_groups(shared + unrelated) == shared_groups(
        shared + unrelated + [report("z-extra", ["person-extra"])]
    )


def test_higher_level_candidates_inherit_source_entity_anchors():
    child_anchors = {
        "leaf-a": frozenset({"person-a", "organization-shared"}),
        "leaf-b": frozenset({"person-b", "organization-shared"}),
    }
    report = {
        "key": "parent-a",
        "dependency": {"children": [{"key": "leaf-a"}]},
        "payload": {"level": 1, "groups": []},
    }
    assert report_anchors(report, child_anchors) == child_anchors["leaf-a"]

    parents = [
        {
            "key": key,
            "payload": {
                "level": 1,
                "groups": [
                    {
                        "id": f"community-{key}",
                        "title": key,
                        "summary": "",
                        "members": [f"leaf-{key}"],
                        "claims": [],
                    }
                ],
            },
        }
        for key in ("a", "b")
    ]
    inherited = {
        "a": child_anchors["leaf-a"],
        "b": child_anchors["leaf-b"],
    }
    assert [
        [item["key"] for item in group]
        for group in _bounded_groups(parents, 2, inherited)
    ] == [["a", "b"]]


def test_isolated_leaf_stays_queryable_without_redundant_parent(tmp_path):
    factory, _ = make_factory(tmp_path)
    factory.store.retire_source("assembly:2")
    sources = []
    for number in range(3):
        batch = fixture_batch()
        batch["documents"][0]["recordKey"] = str(number + 10)
        batch["entities"][0]["id"] = f"person-{number}"
        batch["entities"][1]["id"] = "shared-bill" if number < 2 else "isolated-bill"
        sources.append(sources_from_batch(batch)[0])
    factory.store.put_sources(sources)
    drain(factory, cycles=40)

    reports = current_artifacts(factory.store, "community")
    assert len([item for item in reports if item["payload"]["level"] == 0]) == 3
    parents = [item for item in reports if item["payload"]["level"] > 0]
    assert len(parents) == 1
    assert len(parents[0]["dependency"]["children"]) == 2


def test_legacy_parent_is_hidden_and_retired_before_new_hierarchy_finishes(tmp_path):
    factory, _ = make_factory(tmp_path)
    batch = fixture_batch()
    batch["documents"][0]["recordKey"] = "3"
    batch["entities"][0]["id"] = "another-person"
    factory.store.put_sources([sources_from_batch(batch)[0]])
    drain(factory, cycles=40)
    parents = [
        item
        for item in current_artifacts(factory.store, "community")
        if item["payload"]["level"] > 0
    ]
    assert parents
    assert parents[0]["dependency"]["routing_version"]
    legacy_dependency = {
        key: value
        for key, value in parents[0]["dependency"].items()
        if key != "routing_version"
    }
    factory.store.put_artifact(
        "community", "parent:1:legacy", legacy_dependency, parents[0]["payload"]
    )
    assert factory.store.get_artifact("community", "parent:1:legacy") is not None
    assert all(
        item["key"] != "parent:1:legacy"
        for item in current_artifacts(factory.store, "community")
    )
    reconcile(factory.store)
    assert factory.store.get_artifact("community", "parent:1:legacy") is None
    completed = next(
        job
        for job in factory.store.jobs(kind="community")
        if job["context"].get("artifact_key") == parents[0]["key"]
        and job["result"] is not None
    )
    stale_job = {
        **completed,
        "context": {**completed["context"], "artifact_key": "parent:1:legacy"},
    }
    stale_job["context"].pop("routing_version")
    factory.project(stale_job)
    assert factory.store.get_artifact("community", "parent:1:legacy") is None
