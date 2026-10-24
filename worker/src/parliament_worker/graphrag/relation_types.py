"""Typed directions and historical edge pruning for private graph links."""

from typing import Any

RELATION_TYPES = frozenset(
    {
        "lead_sponsor",
        "co_sponsor",
        "speaker",
        "voter",
        "scheduled_participant",
        "publisher",
        "implementing_agency",
        "committee_proposer",
        "incorporated_into_alternative",
        "concerns",
        "records",
        "holds_office",
    }
)
RELATION_ENDPOINTS = {
    "lead_sponsor": {("person", "bill"), ("person", "activity")},
    "co_sponsor": {("person", "bill"), ("person", "activity")},
    "speaker": {("person", "activity")},
    "voter": {("person", "activity")},
    "scheduled_participant": {("person", "activity")},
    "publisher": {
        ("organization", "activity"),
        ("organization", "bill"),
        ("organization", "policy"),
    },
    "implementing_agency": {
        ("organization", "activity"),
        ("organization", "bill"),
        ("organization", "policy"),
    },
    "committee_proposer": {
        ("organization", "activity"),
        ("organization", "bill"),
        ("organization", "policy"),
    },
    "incorporated_into_alternative": {("bill", "bill")},
    "concerns": {("bill", "policy"), ("activity", "policy")},
    "records": {("document", "activity")},
    "holds_office": {("person", "organization")},
}
EXTRACTABLE_KINDS = frozenset({"person", "organization", "bill", "policy"})
EXTRACTABLE_RELATION_TYPES = frozenset(
    relation_type
    for relation_type, endpoints in RELATION_ENDPOINTS.items()
    if any(set(pair) <= EXTRACTABLE_KINDS for pair in endpoints)
)
OFFICE_TITLES = frozenset(
    {
        "대통령",
        "국무총리",
        "국회의원",
        "의장",
        "부의장",
        "위원장",
        "부위원장",
        "사무총장",
        "사무처장",
        "장관",
        "차관",
        "청장",
        "처장",
        "원장",
        "시장",
        "군수",
        "구청장",
        "도지사",
    }
)


def valid_relation_endpoints(
    relation_type: str, subject_kind: str, target_kind: str
) -> bool:
    """Require the same typed relationship direction as the public knowledge model."""
    return (subject_kind, target_kind) in RELATION_ENDPOINTS.get(relation_type, set())


def prune_invalid_graph_edges(graph: dict[str, Any]) -> dict[str, Any]:
    """Remove unsupported candidate offices and edges before graph activation."""
    nodes = [
        node
        for node in graph["nodes"]
        if not (
            node["kind"] == "organization"
            and node["id"].startswith("candidate_")
            and node["name"].strip() in OFFICE_TITLES
        )
    ]
    kinds = {node["id"]: node["kind"] for node in nodes}
    edges = [
        edge
        for edge in graph["edges"]
        if edge["source"] in kinds
        and edge["target"] in kinds
        and valid_relation_endpoints(
            edge["type"], kinds.get(edge["source"], ""), kinds.get(edge["target"], "")
        )
    ]
    return (
        graph
        if len(nodes) == len(graph["nodes"]) and len(edges) == len(graph["edges"])
        else {**graph, "nodes": nodes, "edges": edges}
    )
