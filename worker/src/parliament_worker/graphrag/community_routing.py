"""Route source-bound community candidates without deciding their membership."""

from collections import Counter, defaultdict
from typing import Any

from parliament_worker.graphrag.prompts import community_task

MAX_SHARED_ANCHOR_DEGREE = 50
ROUTING_VERSION = "source-entity-overlap-fixed-hub-cap-v3"


def report_anchors(
    artifact: dict[str, Any], child_anchors: dict[str, frozenset[str]]
) -> frozenset[str]:
    """Carry original entity IDs through model-produced report levels.

    Args:
        artifact: Current model-produced community report.
        child_anchors: Entity IDs already traced to its exact child reports.

    Returns:
        Source-bound entity IDs shared by the report and its descendants.
    """
    if artifact["payload"]["level"] == 0:
        return frozenset(
            member
            for group in artifact["payload"]["groups"]
            for member in group["members"]
        )
    return frozenset(
        anchor
        for child in artifact["dependency"].get("children", [])
        for anchor in child_anchors.get(child["key"], frozenset())
    )


def bounded_groups(
    artifacts: list[dict[str, Any]],
    level: int,
    anchors_by_key: dict[str, frozenset[str]] | None = None,
) -> list[list[dict[str, Any]]]:
    """Put reports sharing an evidenced entity into bounded model requests.

    This routing only selects context. The model still assigns communities and
    produces every claim; unrelated reports are not forced into one cluster.

    Args:
        artifacts: Current reports eligible for the next level.
        level: Level of the proposed parent model request.
        anchors_by_key: Original entity IDs inherited through lower levels.

    Returns:
        Deterministic disjoint groups, each fitting the model request limit.
    """
    from parliament_worker.graphrag.index import _community_input

    ordered = sorted(artifacts, key=lambda item: item["key"])
    by_key = {item["key"]: item for item in ordered}
    anchors = {
        key: (
            anchors_by_key[key]
            if anchors_by_key is not None and key in anchors_by_key
            else report_anchors(item, {})
        )
        for key, item in by_key.items()
    }
    frequencies = Counter(value for values in anchors.values() for value in values)
    # Keep this limit independent of corpus size: an unrelated new report must
    # not suddenly reroute existing communities at a percentage boundary.
    routing_anchors = {
        key: frozenset(
            value
            for value in values
            if 1 < frequencies[value] <= MAX_SHARED_ANCHOR_DEGREE
        )
        for key, values in anchors.items()
    }
    postings: dict[str, set[str]] = defaultdict(set)
    for key, values in routing_anchors.items():
        for value in values:
            postings[value].add(key)
    unassigned = set(by_key)
    groups: list[list[dict[str, Any]]] = []
    for seed in ordered:
        seed_key = seed["key"]
        if seed_key not in unassigned:
            continue
        group = [seed]
        unassigned.remove(seed_key)
        related = set().union(*(postings[value] for value in routing_anchors[seed_key]))
        related.discard(seed_key)

        def similarity(key: str) -> float:
            return sum(
                1 / frequencies[value]
                for value in routing_anchors[seed_key] & routing_anchors[key]
            )

        for key in sorted(
            related & unassigned, key=lambda item: (-similarity(item), item)
        ):
            candidate = group + [by_key[key]]
            try:
                members, proofs = _community_input(candidate, level)
                community_task(members, proofs, level=level)
            except ValueError:
                continue
            group = candidate
            unassigned.remove(key)
            if len(group) == 3:
                break
        groups.append(group)
    return groups
