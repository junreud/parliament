"""General links can advance automatically; political acts need human review."""

from typing import Any

GENERAL_TYPES = frozenset({"concerns", "records"})


def apply_review_policy(graph: dict[str, Any]) -> dict[str, Any]:
    """Separate machine eligibility from source/identity/publication permission."""
    nodes = {node["id"]: node for node in graph["nodes"]}
    for edge in graph["edges"]:
        endpoint_verified = all(
            nodes[edge[key]].get("identityStatus") == "source_bound"
            and bool(nodes[edge[key]].get("identifiers"))
            for key in ("source", "target")
        )
        general = edge["type"] in GENERAL_TYPES
        usable = all(
            proof.get("licenseStatus") == "allowed" for proof in edge["evidence"]
        )
        edge["reviewRequired"] = not general
        grounded = (
            edge.get("endpointSupported") is True
            and edge.get("relationCueSupported") is True
        )
        edge["automaticEligibility"] = general and endpoint_verified and grounded
        edge["decision"] = (
            "approved"
            if general and endpoint_verified and usable and grounded
            else "pending"
        )
        edge["publicationBlockedBy"] = (
            []
            if edge["decision"] == "approved"
            else [
                reason
                for reason, blocked in (
                    ("human_role_review", not general),
                    ("identity_review", not endpoint_verified),
                    ("source_use_review", not usable),
                    ("relation_grounding_review", not grounded),
                )
                if blocked
            ]
        )
        edge["approvalMethod"] = (
            "evidence_validation" if edge["decision"] == "approved" else None
        )
    return graph
