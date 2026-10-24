"""Reject model-created office titles masquerading as organizations."""

from parliament_worker.graphrag.relation_types import prune_invalid_graph_edges


def test_candidate_office_title_and_its_relation_are_removed() -> None:
    """A title alone is not evidence of an organization endpoint."""
    graph = {
        "nodes": [
            {"id": "person-1", "kind": "person", "name": "이석준"},
            {"id": "candidate_role", "kind": "organization", "name": "사무총장"},
            {"id": "org-1", "kind": "organization", "name": "국가인권위원회"},
        ],
        "edges": [
            {
                "id": "bad",
                "source": "person-1",
                "target": "candidate_role",
                "type": "holds_office",
            },
            {
                "id": "good",
                "source": "person-1",
                "target": "org-1",
                "type": "holds_office",
            },
        ],
        "public": False,
    }

    pruned = prune_invalid_graph_edges(graph)

    assert [node["id"] for node in pruned["nodes"]] == ["person-1", "org-1"]
    assert [edge["id"] for edge in pruned["edges"]] == ["good"]
    assert pruned["public"] is False


def test_source_bound_office_label_is_preserved() -> None:
    """This correction affects only unverified model-created nodes."""
    graph = {
        "nodes": [
            {"id": "person-1", "kind": "person", "name": "예시"},
            {"id": "org-1", "kind": "organization", "name": "대통령"},
        ],
        "edges": [
            {
                "id": "existing",
                "source": "person-1",
                "target": "org-1",
                "type": "holds_office",
            }
        ],
        "public": False,
    }

    assert prune_invalid_graph_edges(graph) == graph
