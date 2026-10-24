"""Private source-bound identities when no graph extraction is available."""

from typing import Any


def source_only_person_nodes(
    sources: list[dict[str, Any]], *, target_id: str | None = None
) -> dict[str, dict[str, Any]]:
    """Expose input people as pending nodes without inferring any relations.

    Args:
        sources: Active source revisions containing typed input entities.
        target_id: Optional person ID to avoid projecting the entire roster.

    Returns:
        Private candidate nodes; conflicting names for one ID are flagged.
    """
    nodes: dict[str, dict[str, Any]] = {}
    for source in sources:
        for entity in source["payload"]["entities"]:
            if entity.get("kind") != "person" or (
                target_id is not None and entity.get("id") != target_id
            ):
                continue
            identifier = entity["id"]
            existing = nodes.get(identifier)
            if existing:
                if existing["name"] != entity["name"]:
                    existing["identityConflict"] = True
                continue
            nodes[identifier] = {
                "id": identifier,
                "kind": "person",
                "name": entity["name"],
                "identityStatus": "input_unverified",
                "decision": "pending",
                "sourceOnly": True,
            }
    return nodes
