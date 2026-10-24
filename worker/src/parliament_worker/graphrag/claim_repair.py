"""Queue version-pinned repairs for private reports with unsafe prose."""

import json
from copy import deepcopy
from typing import Any

from parliament_worker.graphrag.claim_quality import claim_quality_flags
from parliament_worker.graphrag.community_enrichment import SELECTION_CONTRACT
from parliament_worker.graphrag.index import current_artifacts
from parliament_worker.graphrag.inputs import canonical, fingerprint
from parliament_worker.graphrag.output_contract import ASSIGNMENT_COMMUNITY_CONTRACT
from parliament_worker.graphrag.store import GraphStore

REPAIR_CONTRACT = "parliament-community-claim-quality-repair-v1"
DEPENDENCY_KEYS = (
    "sources",
    "source_manifest",
    "children",
    "model_signature",
    "prompt_version",
    "routing_version",
    "group_id_version",
    "snapshot",
)


def _job_dependency(context: dict[str, Any]) -> dict[str, Any]:
    """Extract only the fields saved in a community artifact dependency."""
    return {key: context[key] for key in DEPENDENCY_KEYS if key in context}


def _flagged(report: dict[str, Any]) -> bool:
    """Check the current report's fixed claims without changing source prose."""
    return any(
        claim_quality_flags(claim["text"], claim["evidence"]["text"])
        for group in report["payload"]["groups"]
        for claim in group["claims"]
    )


def _repair_request(body: dict[str, Any]) -> dict[str, Any]:
    """Create a new immutable request from the original evidence and schema."""
    repaired = deepcopy(body)
    data = json.loads(repaired["messages"][-1]["content"])
    rules = data.get("rules")
    if not isinstance(rules, str) or not isinstance(data.get("sources"), dict):
        raise ValueError("community repair source request is incomplete")
    data["rules"] = (
        rules
        + " No internal IDs like E1 in titles or claims; use member names."
        + " Describe scheduled actions as scheduled, never completed."
        + " Keep every claim tied to its supplied exact source quote."
    )
    repaired["messages"][-1]["content"] = canonical(data).decode()
    return repaired


def plan_claim_repairs(store: GraphStore, model_signature: str, capacity: int) -> int:
    """Queue bounded repairs only after every active source has a graph.

    Args:
        store: Private persistent graph state.
        model_signature: Current verified provider model and revision.
        capacity: Maximum active logical jobs across the factory.

    Returns:
        Number of new repair jobs queued. Prior requests remain immutable.
    """
    graphs = current_artifacts(store, "graph")
    graph_keys = {artifact["key"] for artifact in graphs}
    if any(
        f"{source['scope']}:{unit['id']}" not in graph_keys
        for source in store.sources()
        for unit in source["payload"]["units"]
    ):
        return 0
    status = store.status()
    active = sum(
        status["jobs"][state]
        for state in ("planned", "deferred", "submitting", "polling")
    )
    room = min(64, capacity - active)
    if room <= 0:
        return 0
    jobs = store.jobs(kind="community")
    known = {job["key"] for job in jobs}
    bases = {}
    for job in jobs:
        context = job["context"]
        if (
            job["state"] == "completed"
            and job["result"] is not None
            and context.get("model_signature") == model_signature
            and context.get("output_contract")
            not in {SELECTION_CONTRACT, ASSIGNMENT_COMMUNITY_CONTRACT}
        ):
            bases[
                (context.get("artifact_key"), fingerprint(_job_dependency(context)))
            ] = job
    flagged = [
        report for report in current_artifacts(store, "community") if _flagged(report)
    ]
    leaves = [report for report in flagged if report["payload"]["level"] == 0]
    candidates = leaves or sorted(
        flagged, key=lambda report: report["payload"]["level"]
    )
    planned = []
    for report in candidates:
        key = fingerprint([REPAIR_CONTRACT, report["key"], report["version"]])
        if key in known:
            continue
        base = bases.get((report["key"], fingerprint(report["dependency"])))
        if base is None:
            continue
        context = deepcopy(base["context"])
        context["quality_repair_for_version"] = report["version"]
        context["quality_repair_contract"] = REPAIR_CONTRACT
        planned.append(
            {
                "kind": "community",
                "key": key,
                "request": _repair_request(base["request"]),
                "context": context,
            }
        )
        if len(planned) >= room:
            break
    if planned:
        store.enqueue_many(planned)
    return len(planned)
