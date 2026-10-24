"""Structural coverage must distinguish source units from derived repairs."""

import argparse
import json
from importlib import import_module

from parliament_worker.graphrag.index import _windows
from parliament_worker.graphrag.inputs import fingerprint
from parliament_worker.graphrag.prompts import GROUP_ID_VERSION


def test_coverage_separates_missing_source_graph_from_extra_repair_graph():
    audit_coverage = import_module("parliament_worker.graphrag.coverage").audit_coverage
    source = {
        "scope": "official-roster",
        "fingerprint": "revision-a",
        "generation": 1,
        "payload": {"units": [{"id": "u1"}, {"id": "u2"}]},
    }
    dependency = {
        "sources": [
            {"scope": "official-roster", "fingerprint": "revision-a", "generation": 1}
        ]
    }
    graph = {
        "kind": "graph",
        "key": "official-roster:u1",
        "version": "graph-v1",
        "dependency": dependency,
        "payload": {
            "nodes": [{"id": "person-a", "name": "가", "kind": "person"}],
            "edges": [{"id": "edge-1", "type": "holds_office"}],
        },
    }
    repair = graph | {
        "key": "official-roster:u1:repair",
        "payload": graph["payload"]
        | {"nodes": [{"id": "person-a", "name": "나", "kind": "person"}]},
    }
    leaf_key = _windows([graph])[0][0]
    leaf = {
        "kind": "community",
        "key": leaf_key,
        "version": "leaf-v1",
        "dependency": dependency
        | {
            "group_id_version": GROUP_ID_VERSION,
            "children": [
                {"kind": "graph", "key": graph["key"], "version": graph["version"]}
            ],
        },
        "payload": {"level": 0, "groups": []},
    }
    snapshot = {
        "sources": [source],
        "model": None,
        "artifacts": {"graph": [graph, repair], "community": [leaf]},
    }

    result = audit_coverage(snapshot)

    assert result["sourceUnits"] == 2
    assert result["currentSourceGraphs"] == 1
    assert result["missingSourceGraphs"] == 1
    assert result["derivedGraphs"] == 1
    assert result["expectedLeaves"] == 2
    assert result["currentLeaves"] == 1
    assert result["missingLeaves"] == 1
    assert result["parentReportsByLevel"] == {}
    assert result["membershipOnlyReportsByLevel"] == {}
    assert result["baseGraphAndLeafReady"] is False
    assert result["edgeTypes"] == {"holds_office": 1}
    assert result["sourcePrefixes"] == {"official-roster": 1}
    assert result["nodeKinds"] == {"person": 1}
    assert result["identityConflictIds"] == 1
    assert result["public"] is False


def test_coverage_command_writes_a_private_snapshot(tmp_path):
    cli = import_module("parliament_worker.graphrag.cli")
    parser = argparse.ArgumentParser()
    cli.add_parser(parser.add_subparsers(dest="command", required=True))
    output = tmp_path / "coverage.json"
    args = parser.parse_args(
        [
            "graphrag",
            "audit-coverage",
            "--state",
            str(tmp_path / "state"),
            "--output",
            str(output),
        ]
    )

    assert cli.run(args, parser) == 0
    report = json.loads(output.read_text())
    assert report["schema"] == "parliament-graphrag-coverage-v1"
    assert report["sourceUnits"] == 0
    assert report["baseGraphAndLeafReady"] is False
    assert report["completionClaim"] == "unverified"
    assert output.stat().st_mode & 0o077 == 0


def test_coverage_distinguishes_registered_people_from_model_mentions():
    audit_coverage = import_module("parliament_worker.graphrag.coverage").audit_coverage
    source = {
        "scope": "official-roster",
        "fingerprint": "revision-a",
        "generation": 1,
        "payload": {
            "units": [{"id": "u1"}],
            "entities": [
                {"id": "person-linked", "name": "가", "kind": "person"},
                {"id": "person-source-only", "name": "나", "kind": "person"},
            ],
        },
    }
    graph = {
        "kind": "graph",
        "key": "official-roster:u1",
        "version": "graph-v1",
        "dependency": {
            "sources": [
                {
                    "scope": "official-roster",
                    "fingerprint": "revision-a",
                    "generation": 1,
                }
            ]
        },
        "payload": {
            "nodes": [
                {"id": "person-linked", "name": "가", "kind": "person"},
                {"id": "person-mention", "name": "다", "kind": "person"},
                {"id": "office", "name": "기관", "kind": "organization"},
            ],
            "edges": [
                {
                    "id": "office-edge",
                    "source": "person-linked",
                    "target": "office",
                    "type": "holds_office",
                }
            ],
        },
    }
    snapshot = {
        "sources": [source],
        "model": None,
        "artifacts": {"graph": [graph], "community": []},
    }

    assert audit_coverage(snapshot)["personCoverage"] == {
        "registeredSourceIds": 2,
        "registeredInGraph": 1,
        "registeredSourceOnly": 1,
        "modelAddedMentionNodes": 1,
        "registeredGraphNodesWithoutEdges": 0,
        "modelAddedMentionNodesWithoutEdges": 1,
    }


def test_coverage_requires_parent_reports_for_linked_leaves():
    audit_coverage = import_module("parliament_worker.graphrag.coverage").audit_coverage
    source = {
        "scope": "official-roster",
        "fingerprint": "revision-a",
        "generation": 1,
        "payload": {"units": [{"id": "u1"}, {"id": "u2"}]},
    }
    dependency = {
        "sources": [
            {key: source[key] for key in ("scope", "fingerprint", "generation")}
        ]
    }
    graphs = [
        {
            "kind": "graph",
            "key": f"official-roster:u{number}",
            "version": f"graph-v{number}",
            "dependency": dependency,
            "payload": {
                "nodes": [{"id": "person-a", "name": "가", "kind": "person"}],
                "edges": [],
            },
        }
        for number in (1, 2)
    ]
    leaves = [
        {
            "kind": "community",
            "key": key,
            "version": f"leaf-v{number}",
            "dependency": dependency
            | {
                "group_id_version": GROUP_ID_VERSION,
                "children": [
                    {"kind": "graph", "key": item["key"], "version": item["version"]}
                ],
            },
            "payload": {
                "level": 0,
                "groups": [
                    {
                        "id": f"group-{number}",
                        "title": "공통 인물",
                        "summary": "",
                        "members": ["person-a"],
                        "claims": [],
                    }
                ],
            },
        }
        for number, (key, items) in enumerate(_windows(graphs), 1)
        for item in items
    ]
    snapshot = {
        "sources": [source],
        "model": None,
        "artifacts": {"graph": graphs, "community": leaves},
    }

    before = audit_coverage(snapshot)
    assert before["baseGraphAndLeafReady"] is True
    assert before["expectedParentReportsByLevel"] == {"1": 1}
    assert before["missingParentReportsByLevel"] == {"1": 1}
    assert before["hierarchyReady"] is False

    ordered = sorted(leaves, key=lambda item: item["key"])
    parent_key = "parent:1:" + fingerprint([item["key"] for item in ordered])
    snapshot["artifacts"]["community"] = leaves + [
        {
            "kind": "community",
            "key": parent_key,
            "version": "parent-v1",
            "dependency": dependency
            | {
                "group_id_version": GROUP_ID_VERSION,
                "children": [
                    {
                        "kind": "community",
                        "key": item["key"],
                        "version": item["version"],
                    }
                    for item in ordered
                ],
                "routing_version": "source-entity-overlap-fixed-hub-cap-v3",
            },
            "payload": {
                "level": 1,
                "groups": [
                    {"id": "parent-group", "members": ["group-1"], "claims": []}
                ],
                "reportStatus": "membership_only",
            },
        }
    ]
    after = audit_coverage(snapshot)
    assert after["missingParentReportsByLevel"] == {"1": 0}
    assert after["membershipOnlyReportsByLevel"] == {"1": 1}
    assert after["claimFreeParentGroupsByLevel"] == {"1": 1}
    assert after["hierarchyReady"] is True
