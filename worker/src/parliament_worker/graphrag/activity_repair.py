"""Ask the inference server to verify source-bound activity role candidates."""

from typing import Any

from parliament_worker.graphrag.index import source_dependency
from parliament_worker.graphrag.inputs import fingerprint
from parliament_worker.graphrag.prompts import PROMPT_VERSION, request
from parliament_worker.graphrag.relation_types import valid_relation_endpoints
from parliament_worker.graphrag.source_forms import source_form
from parliament_worker.graphrag.store import GraphStore

ACTIVITY_CONTRACT = "official-activity-role-v1"
ACTIVE_STATES = frozenset({"planned", "deferred", "submitting", "polling"})


def _parts(
    source: dict[str, Any], candidate: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]] | None:
    """Resolve one actor, one activity and its complete fixed source units."""
    payload = source["payload"]
    if candidate not in payload.get("activityRelationCandidates", []):
        return None
    actor = next(
        (item for item in payload["entities"] if item["id"] == candidate["subjectId"]),
        None,
    )
    activity = next(
        (
            item
            for item in payload.get("activityCandidates", [])
            if item["id"] == candidate["objectId"]
        ),
        None,
    )
    if (
        actor is None
        or activity is None
        or not valid_relation_endpoints(candidate["type"], actor["kind"], "activity")
        or candidate["type"] == "scheduled_participant"
        and activity["stage"] != "scheduled"
    ):
        return None
    by_id = {unit["id"]: unit for unit in payload["units"]}
    units = [by_id.get(identifier) for identifier in candidate["unitIds"]]
    if not units or any(unit is None for unit in units):
        return None
    return actor, activity, units


def _request(
    candidate: dict[str, Any],
    actor: dict[str, Any],
    activity: dict[str, Any],
    units: list[dict[str, Any]],
) -> dict[str, Any]:
    """Request one strict yes/no decision without asking the model to invent IDs."""
    body = request(
        "verify official activity role",
        {
            "candidate": {
                "actor": actor["name"],
                "actorKind": actor["kind"],
                "activity": activity["name"],
                "activityStage": activity["stage"],
                "relation": candidate["type"],
            },
            "source": {
                f"U{index + 1}": unit["text"] for index, unit in enumerate(units)
            },
            "rules": (
                "Return supported=true only if the supplied official passage "
                "explicitly supports the actor's named role in this activity. "
                "A matching topic, name mention, or job title alone is insufficient. "
                "For scheduled_participant, the passage must state planned "
                "participation; do not claim that the event occurred. "
                "For publisher, require explicit attribution to the named agency. "
                "Do not infer policy outcomes or a person's credit."
            ),
        },
        output_tokens=128,
    )
    body["response_format"] = {
        "type": "json_schema",
        "json_schema": {
            "name": "activity_role",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {"supported": {"type": "boolean"}},
                "required": ["supported"],
                "additionalProperties": False,
            },
        },
    }
    return body


def validate_activity_link(
    output: dict[str, Any], context: dict[str, Any], source: dict[str, Any]
) -> dict[str, Any]:
    """Materialize a positive remote decision as a private review candidate.

    Args:
        output: Strict model decision.
        context: Persisted source dependency, candidate and proof units.
        source: Current source revision.

    Returns:
        Pending activity graph; a negative judgment has no edge.
    """
    if set(output) != {"supported"} or type(output["supported"]) is not bool:
        raise ValueError("invalid activity role response")
    if context.get("sources") != [source_dependency(source)]:
        raise ValueError("activity source dependency mismatch")
    candidate = context.get("candidate")
    if not isinstance(candidate, dict):
        raise ValueError("invalid activity candidate")
    selected = _parts(source, candidate)
    if selected is None or context.get("source_units") != selected[2]:
        raise ValueError("activity source proof mismatch")
    actor, activity, units = selected
    if output["supported"] and not any(
        source_form(unit["text"], actor["name"]) for unit in units
    ):
        raise ValueError("activity actor absent from fixed proof")
    nodes = [
        {**actor, "identityStatus": "source_bound"},
        {
            "id": activity["id"],
            "kind": "activity",
            "name": activity["name"],
            "stage": activity["stage"],
            "activityType": activity["type"],
            "activityVersion": activity["version"],
            "identifiers": [],
            "identityStatus": "source_bound",
        },
    ]
    edges = []
    if output["supported"]:
        edge = {
            "source": actor["id"],
            "target": activity["id"],
            "type": candidate["type"],
            "activityStage": activity["stage"],
            "evidence": units,
            "decision": "pending",
            "endpointSupported": True,
            "relationCueSupported": True,
        }
        edges.append({"id": "edge_" + fingerprint(edge), **edge})
    return {"nodes": nodes, "edges": edges, "public": False}


def plan_activity_links(store: GraphStore, model_signature: str, capacity: int) -> int:
    """Queue one durable remote judgment per source-bound activity role."""
    jobs = store.jobs()
    room = capacity - sum(job["state"] in ACTIVE_STATES for job in jobs)
    if room <= 0:
        return 0
    known = {(job["kind"], job["key"]) for job in jobs}
    planned = []
    for source in store.sources():
        dependency = source_dependency(source)
        for candidate in source["payload"].get("activityRelationCandidates", []):
            selected = _parts(source, candidate)
            if selected is None:
                continue
            actor, activity, units = selected
            key = fingerprint(
                [
                    dependency,
                    candidate,
                    [unit["id"] for unit in units],
                    model_signature,
                    PROMPT_VERSION,
                    ACTIVITY_CONTRACT,
                ]
            )
            if ("extract", key) in known:
                continue
            planned.append(
                {
                    "kind": "extract",
                    "key": key,
                    "request": _request(candidate, actor, activity, units),
                    "context": {
                        "relation_task": "activity_role",
                        "output_contract": ACTIVITY_CONTRACT,
                        "sources": [dependency],
                        "candidate": candidate,
                        "source_units": units,
                        "artifact_key": "activity_"
                        + fingerprint([source["scope"], candidate]),
                        "model_signature": model_signature,
                        "prompt_version": PROMPT_VERSION,
                    },
                }
            )
            known.add(("extract", key))
            if len(planned) >= room:
                store.enqueue_many(planned)
                return len(planned)
    if planned:
        store.enqueue_many(planned)
    return len(planned)
