"""Read-only structural coverage for the private GraphRAG factory."""

from collections import Counter
from typing import Any

from parliament_worker.graphrag.community_routing import bounded_groups, report_anchors
from parliament_worker.graphrag.index import _windows, select_snapshot_artifacts
from parliament_worker.graphrag.inputs import fingerprint


def _hierarchy_coverage(
    communities: list[dict[str, Any]], expected_leaves: set[str]
) -> tuple[dict[str, int], dict[str, int], bool]:
    """Count the next required report level using the factory's current routing."""
    reports = {artifact["key"]: artifact for artifact in communities}
    if not expected_leaves or not expected_leaves <= reports.keys():
        return {}, {}, False
    children = [reports[key] for key in sorted(expected_leaves)]
    anchors = {item["key"]: report_anchors(item, {}) for item in children}
    expected_by_level: dict[str, int] = {}
    missing_by_level: dict[str, int] = {}
    for level in range(1, 9):
        groups = [
            group
            for group in bounded_groups(children, level, anchors)
            if len(group) > 1
        ]
        if not groups:
            return expected_by_level, missing_by_level, True
        keys = [
            f"parent:{level}:{fingerprint([item['key'] for item in group])}"
            for group in groups
        ]
        present = [reports[key] for key in keys if key in reports]
        expected_by_level[str(level)] = len(keys)
        missing_by_level[str(level)] = len(keys) - len(present)
        if len(present) != len(keys):
            return expected_by_level, missing_by_level, False
        for item in present:
            anchors[item["key"]] = report_anchors(item, anchors)
        children = present
    return expected_by_level, missing_by_level, len(children) <= 1


def audit_coverage(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Count current source, graph, and community artifacts in one snapshot.

    Args:
        snapshot: Consistent GraphStore query snapshot, including active sources.

    Returns:
        Structural coverage counts. This does not approve model claims or prove
        that all politicians or public records have been collected.
    """
    graphs = select_snapshot_artifacts(snapshot, "graph")
    communities = select_snapshot_artifacts(snapshot, "community")
    source_units = {
        f"{source['scope']}:{unit['id']}"
        for source in snapshot["sources"]
        for unit in source["payload"]["units"]
    }
    graph_keys = {artifact["key"] for artifact in graphs}
    expected_leaves = {key for key, _ in _windows(graphs)}
    leaves = {
        artifact["key"] for artifact in communities if artifact["payload"]["level"] == 0
    }
    parent_levels = Counter(
        artifact["payload"]["level"]
        for artifact in communities
        if artifact["payload"]["level"] > 0
    )
    membership_only_levels = Counter(
        artifact["payload"]["level"]
        for artifact in communities
        if artifact["payload"].get("reportStatus") == "membership_only"
    )
    claim_free_parent_groups = Counter(
        artifact["payload"]["level"]
        for artifact in communities
        if artifact["payload"]["level"] > 0
        for group in artifact["payload"]["groups"]
        if not group["claims"]
    )
    edges = {
        edge["id"]: edge for artifact in graphs for edge in artifact["payload"]["edges"]
    }
    edge_types = Counter(edge["type"] for edge in edges.values())
    source_prefixes = Counter(
        source["scope"].split(":", 1)[0] for source in snapshot["sources"]
    )
    nodes: dict[str, dict[str, Any]] = {}
    identity_conflicts = set()
    for artifact in graphs:
        for node in artifact["payload"]["nodes"]:
            prior = nodes.setdefault(node["id"], node)
            if (prior["kind"], prior["name"]) != (node["kind"], node["name"]):
                identity_conflicts.add(node["id"])
    node_kinds = Counter(node["kind"] for node in nodes.values())
    registered_people = {
        entity["id"]
        for source in snapshot["sources"]
        for entity in source["payload"].get("entities", [])
        if entity.get("kind") == "person"
    }
    graph_people = {
        identifier for identifier, node in nodes.items() if node["kind"] == "person"
    }
    incident_nodes = {
        identifier
        for edge in edges.values()
        for identifier in (edge.get("source"), edge.get("target"))
        if isinstance(identifier, str)
    }
    registered_graph_people = registered_people & graph_people
    model_added_mentions = graph_people - registered_people
    expected_parents, missing_parents, hierarchy_ready = _hierarchy_coverage(
        communities, expected_leaves
    )
    return {
        "schema": "parliament-graphrag-coverage-v1",
        "public": False,
        "sourceCount": len(snapshot["sources"]),
        "sourceUnits": len(source_units),
        "currentSourceGraphs": len(source_units & graph_keys),
        "missingSourceGraphs": len(source_units - graph_keys),
        "derivedGraphs": len(graph_keys - source_units),
        "expectedLeaves": len(expected_leaves),
        "currentLeaves": len(expected_leaves & leaves),
        "missingLeaves": len(expected_leaves - leaves),
        "parentReportsByLevel": {
            str(level): count for level, count in sorted(parent_levels.items())
        },
        "membershipOnlyReportsByLevel": {
            str(level): count for level, count in sorted(membership_only_levels.items())
        },
        "claimFreeParentGroupsByLevel": {
            str(level): count
            for level, count in sorted(claim_free_parent_groups.items())
        },
        "expectedParentReportsByLevel": expected_parents,
        "missingParentReportsByLevel": missing_parents,
        "hierarchyReady": hierarchy_ready and not (source_units - graph_keys),
        "baseGraphAndLeafReady": bool(source_units)
        and not (source_units - graph_keys)
        and not (expected_leaves - leaves),
        "edgeTypes": dict(sorted(edge_types.items())),
        "sourcePrefixes": dict(sorted(source_prefixes.items())),
        "nodeKinds": dict(sorted(node_kinds.items())),
        "personCoverage": {
            "registeredSourceIds": len(registered_people),
            "registeredInGraph": len(registered_graph_people),
            "registeredSourceOnly": len(registered_people - graph_people),
            "modelAddedMentionNodes": len(model_added_mentions),
            "registeredGraphNodesWithoutEdges": len(
                registered_graph_people - incident_nodes
            ),
            "modelAddedMentionNodesWithoutEdges": len(
                model_added_mentions - incident_nodes
            ),
        },
        "identityConflictIds": len(identity_conflicts),
        "completionClaim": "unverified",
    }
