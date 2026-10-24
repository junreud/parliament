"""Project reviewed input activity roles onto exact private source units."""

from typing import Any

from parliament_worker.graphrag.relation_types import valid_relation_endpoints


def _covering_units(evidence: dict[str, Any], units: list[dict[str, Any]]) -> list[str]:
    """Find a contiguous set of fixed units covering one evidence interval."""
    matching = sorted(
        (
            unit
            for unit in units
            if all(
                unit[key] == evidence[key]
                for key in (
                    "documentId",
                    "documentVersion",
                    "extractionVersion",
                    "segmentId",
                )
            )
            and unit["start"] < evidence["end"]
            and evidence["start"] < unit["end"]
        ),
        key=lambda unit: unit["start"],
    )
    cursor = evidence["start"]
    chosen = []
    for unit in matching:
        if unit["start"] > cursor:
            return []
        if unit["end"] > cursor:
            chosen.append(unit["id"])
            cursor = unit["end"]
        if cursor >= evidence["end"]:
            return chosen
    return []


def project_activity_roles(
    batch: dict[str, Any],
    document: dict[str, Any],
    selected: list[dict[str, Any]],
    units: list[dict[str, Any]],
    entities: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Keep only source-local activity roles with complete fixed proof intervals.

    Args:
        batch: Validated knowledge batch containing activity and role candidates.
        document: The official document represented by this source revision.
        selected: Evidence records pinned to that document revision.
        units: Retained text units; restricted content is already omitted.
        entities: Typed, source-local people and organizations.

    Returns:
        Activity identities and source-bound relation candidates, or an empty map.
    """
    activities = {activity["id"]: activity for activity in batch.get("activities", [])}
    proofs = {item["id"]: item for item in selected}
    candidates: dict[str, dict[str, Any]] = {}
    relations = []
    for relation in batch.get("relations", []):
        if relation.get("decision") == "rejected":
            continue
        actor = entities.get(relation.get("subjectId"))
        activity = activities.get(relation.get("objectId"))
        if (
            not actor
            or not activity
            or activity.get("sourceUrl") != document["sourceUrl"]
            or not valid_relation_endpoints(
                relation.get("type", ""), actor["kind"], "activity"
            )
            or relation["type"] == "scheduled_participant"
            and activity.get("stage") != "scheduled"
        ):
            continue
        title = activity.get("title")
        if not isinstance(title, str) or not 1 <= len(title) <= 300:
            raise ValueError("invalid fixed activity title")
        proof_ids = relation.get("evidenceIds", [])
        if not proof_ids or any(identifier not in proofs for identifier in proof_ids):
            continue
        covered = [
            _covering_units(proofs[identifier], units) for identifier in proof_ids
        ]
        if any(not group for group in covered):
            continue
        unit_ids = sorted({identifier for group in covered for identifier in group})
        candidates[activity["id"]] = {
            "id": activity["id"],
            "name": title,
            "type": activity.get("type"),
            "stage": activity.get("stage"),
            "version": activity.get("version"),
        }
        relations.append(
            {
                "type": relation["type"],
                "subjectId": actor["id"],
                "objectId": activity["id"],
                "unitIds": unit_ids,
            }
        )
    if not relations:
        return {}
    return {
        "activityCandidates": [candidates[key] for key in sorted(candidates)],
        "activityRelationCandidates": sorted(
            relations,
            key=lambda item: (item["type"], item["subjectId"], item["objectId"]),
        ),
    }
