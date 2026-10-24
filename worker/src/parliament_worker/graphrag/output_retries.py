"""Schedule evidence-preserving retries of terminal model failures."""

import time
from copy import deepcopy
from typing import Any

from parliament_worker.graphrag.claim_selection import (
    CLAIM_SELECTION_CONTRACT,
    SOURCE_GROUP_SELECTION_CONTRACT,
    selection_retry_request,
)
from parliament_worker.graphrag.community_enrichment import SELECTION_CONTRACT
from parliament_worker.graphrag.community_retry import (
    QUOTE_OPTIONS_COMMUNITY_CONTRACT,
    SHORT_QUOTE_COMMUNITY_CONTRACT,
    assignment_community_contract,
    precise_community_contract,
    quote_options_community_contract,
    short_quote_community_contract,
)
from parliament_worker.graphrag.index import (
    children_current,
    dependencies_current,
    routing_current,
)
from parliament_worker.graphrag.inputs import fingerprint
from parliament_worker.graphrag.output_contract import (
    ANSWER_CONTRACT,
    ASSIGNMENT_COMMUNITY_CONTRACT,
    COMPLETE_COMMUNITY_CONTRACT,
    DIRECTIONAL_CONTRACT,
    LEGACY_ANSWER_CONTRACT,
    OUTPUT_CONTRACT,
    PRECISE_COMMUNITY_CONTRACT,
    answer_selector_contract,
    complete_community_contract,
    directional_extraction_contract,
    enforce_output_contract,
)
from parliament_worker.graphrag.prompts import PROMPT_VERSION
from parliament_worker.graphrag.store import GraphStore
from parliament_worker.graphrag.store_schema import MAX_SNAPSHOT_BYTES

OUTPUT_FAILURES = frozenset(
    {
        "generated_content_validation_failed",
        "inference_completion_invalid",
        "remote_inference_failed",
    }
)
ARTIFACT_KINDS = {
    "extract": "graph",
    "community": "community",
    "query_map": "answer_map",
    "query_local": "answer",
    "query_reduce": "answer",
}
ACTIVE_STATES = frozenset({"planned", "deferred", "submitting", "polling"})
RETRY_VERSION = "parliament-graph-continuous-retry-v10"
STORAGE_RESERVE_BYTES = 8_000_000


def _short_quote_retry(job: dict[str, Any], attempt: int) -> bool:
    """Use the proven bounded-quote variant only after a first length failure."""
    return (
        job["kind"] == "community"
        and attempt == 1
        and job["error"] == "inference_completion_invalid"
        and job["metadata"].get("validation_reason") == "completion_length_exhausted"
        and job["context"].get("output_contract") != SELECTION_CONTRACT
    )


def _quote_options_retry(job: dict[str, Any], attempt: int) -> bool:
    """Choose fixed source spans after a free-form short quote fails."""
    return (
        job["kind"] == "community"
        and attempt == 2
        and job["context"].get("output_contract") == SHORT_QUOTE_COMMUNITY_CONTRACT
        and bool(job["context"].get("units"))
        and (
            (
                job["error"] == "inference_completion_invalid"
                and job["metadata"].get("validation_reason")
                == "completion_length_exhausted"
            )
            or (
                job["error"] == "generated_content_validation_failed"
                and job["metadata"].get("validation_reason")
                == "graph_quote_absent_or_ambiguous"
            )
        )
    )


def _assignment_retry(job: dict[str, Any], attempt: int) -> bool:
    """Use claim-free membership after repeated constrained failures."""
    return (
        job["kind"] == "community"
        and job["context"].get("output_contract") != SELECTION_CONTRACT
        and (
            attempt >= 6
            or job["error"] == "inference_request_context_limit"
            or (
                attempt >= 5
                and job["error"] == "generated_content_validation_failed"
                and job["metadata"].get("validation_reason")
                in {
                    "unknown_or_duplicate_community_member",
                    "community_membership_incomplete",
                }
            )
            or (
                attempt >= 3
                and job["context"].get("output_contract")
                == QUOTE_OPTIONS_COMMUNITY_CONTRACT
            )
        )
    )


def _retry_contract(job: dict[str, Any], attempt: int) -> str:
    """Keep persisted request and declared output contracts in sync."""
    context = job["context"]
    if context.get("output_contract") == SELECTION_CONTRACT:
        return SELECTION_CONTRACT
    if _short_quote_retry(job, attempt):
        return SHORT_QUOTE_COMMUNITY_CONTRACT
    if _quote_options_retry(job, attempt):
        return QUOTE_OPTIONS_COMMUNITY_CONTRACT
    if (
        job["kind"] == "extract"
        and attempt >= 2
        and context.get("relation_task")
        not in {"bill_lineage", "bill_policy", "ex_officio_chair"}
    ):
        return DIRECTIONAL_CONTRACT
    if _assignment_retry(job, attempt):
        return ASSIGNMENT_COMMUNITY_CONTRACT
    if job["kind"] == "community" and attempt >= 4:
        return PRECISE_COMMUNITY_CONTRACT
    if job["kind"] == "community" and attempt >= 2:
        return COMPLETE_COMMUNITY_CONTRACT
    if job["kind"] in {"query_local", "query_map", "query_reduce"}:
        return (
            context["output_contract"]
            if context.get("output_contract")
            in {CLAIM_SELECTION_CONTRACT, SOURCE_GROUP_SELECTION_CONTRACT}
            else ANSWER_CONTRACT
        )
    return context.get("output_contract", OUTPUT_CONTRACT)


def _next_request(job: dict[str, Any], attempt: int) -> dict[str, Any]:
    """Keep the proof schema while varying repeated deterministic generations."""
    if job["context"].get("output_contract") == SELECTION_CONTRACT:
        request = deepcopy(job["request"])
    elif job["context"].get("relation_task") in {
        "bill_lineage",
        "bill_policy",
        "ex_officio_chair",
    }:
        request = deepcopy(job["request"])
    elif _short_quote_retry(job, attempt):
        request = short_quote_community_contract(job["request"])
    elif _quote_options_retry(job, attempt):
        request = quote_options_community_contract(job["request"])
    elif job["kind"] == "extract" and attempt >= 2:
        request = directional_extraction_contract(job["request"])
    elif _assignment_retry(job, attempt):
        request = assignment_community_contract(job["request"])
    elif job["kind"] == "community" and attempt >= 4:
        request = precise_community_contract(job["request"])
    elif job["kind"] == "community" and attempt >= 2:
        request = complete_community_contract(job["request"])
    elif job["kind"] in {"query_local", "query_map", "query_reduce"}:
        request = (
            selection_retry_request(job["request"])
            if job["context"].get("output_contract")
            in {CLAIM_SELECTION_CONTRACT, SOURCE_GROUP_SELECTION_CONTRACT}
            else answer_selector_contract(job["request"])
        )
    else:
        request = (
            enforce_output_contract(job["request"])
            if job["kind"]
            in {"extract", "community", "query_local", "query_map", "query_reduce"}
            and job["request"].get("response_format", {}).get("type") != "json_schema"
            else deepcopy(job["request"])
        )
    if attempt > 1 or job["context"].get("output_contract"):
        request["seed"] = int(fingerprint([job["key"], attempt])[:8], 16)
        request["temperature"] = 0.2
    return request


def _active_reduction_map(
    job: dict[str, Any],
    jobs_by_id: dict[str, dict[str, Any]],
    question_roots: dict[str, set[str]],
) -> bool:
    """Recognize a failed map in the question's current reduction round."""
    context = job["context"]
    if job["kind"] != "query_map" or ":reduce:" not in context.get("artifact_key", ""):
        return False
    current = job
    seen: set[str] = set()
    while current["id"] not in seen:
        seen.add(current["id"])
        parent = jobs_by_id.get(current["context"].get("retry_of"))
        if parent is None:
            break
        current = parent
    return current["id"] in question_roots.get(context.get("question_id"), set())


def plan_output_retries(
    store: GraphStore, signature: str, capacity: int, *, now: float | None = None
) -> int:
    """Schedule eligible failed logical work without mutating earlier attempts.

    Args:
        store: Durable private requests, results, and provenance.
        signature: Pinned actual model and revision.
        capacity: Maximum shared pending jobs.
        now: Optional clock for deterministic scheduling tests.

    Returns:
        Number of durable attempts added; no remote calls are made here.
    """
    instant = time.time() if now is None else now
    if store.database.stat().st_size >= MAX_SNAPSHOT_BYTES - STORAGE_RESERVE_BYTES:
        return 0
    jobs = store.jobs()
    jobs_by_id = {job["id"]: job for job in jobs}
    question_roots = {
        question["key"]: set(question["payload"].get("jobs", []))
        for question in store.artifacts("question")
        if question["payload"].get("state") == "queued"
    }
    # A global question can pre-plan thousands of local map jobs. Those jobs have
    # not entered the remote queue and must not starve recovery of one failed map.
    # Reserve capacity for requests already in flight and retries we plan here.
    in_flight = sum(j["state"] in ACTIVE_STATES - {"planned"} for j in jobs)
    retry_waiting = sum(
        j["state"] == "planned" and isinstance(j["context"].get("retry_of"), str)
        for j in jobs
    )
    room = capacity - in_flight - retry_waiting
    if room <= 0:
        return 0
    known = {(j["kind"], j["key"]) for j in jobs}
    descendants = {j["context"].get("retry_of") for j in jobs}
    active_artifacts = {
        (j["kind"], j["context"].get("artifact_key"))
        for j in jobs
        if j["state"] in ACTIVE_STATES
    }
    sources = {s["scope"]: s for s in store.sources(include_payload=False)}
    snapshots = {
        (kind, a["key"]): a
        for kind in set(ARTIFACT_KINDS.values())
        for a in store.artifacts(kind)
    }
    planned: list[dict[str, Any]] = []
    seen_artifacts: set[tuple[str, str]] = set()
    for job in reversed(jobs):
        context = job["context"]
        artifact_key = context.get("artifact_key")
        logical = (job["kind"], artifact_key)
        if (
            job["kind"] not in ARTIFACT_KINDS
            or not isinstance(artifact_key, str)
            or logical in seen_artifacts
            or logical in active_artifacts
            or job["state"] != "failed"
            or (
                job["error"] not in OUTPUT_FAILURES
                and not (
                    job["kind"] == "community"
                    and job["error"] == "inference_request_context_limit"
                )
            )
            or job["metadata"].get("completion_uncertain")
            or job["id"] in descendants
            or context.get("model_signature") != signature
            or context.get("prompt_version", PROMPT_VERSION) != PROMPT_VERSION
            or not dependencies_current(context, sources)
            or not routing_current(job["kind"], context)
            or not children_current(store, context, snapshots=snapshots)
        ):
            continue
        seen_artifacts.add(logical)
        artifact_kind = ARTIFACT_KINDS[job["kind"]]
        current = snapshots.get((artifact_kind, artifact_key))
        repair_version = context.get("quality_repair_for_version")
        if repair_version and (current is None or current["version"] != repair_version):
            continue
        dependency = {
            key: context[key]
            for key in (
                "sources",
                "source_manifest",
                "children",
                "model_signature",
                "prompt_version",
                "routing_version",
                "group_id_version",
                "snapshot",
            )
            if key in context
        }
        if (
            current
            and current["dependency"] == dependency
            and not _active_reduction_map(job, jobs_by_id, question_roots)
            and not repair_version
            and not (
                context.get("output_contract") == SELECTION_CONTRACT
                and current["version"] == context.get("prior_report_version")
            )
        ):
            continue
        previous_attempt = context.get(
            "retry_attempt", int(bool(context.get("retry_of")))
        )
        attempt = previous_attempt + 1
        target_contract = _retry_contract(job, attempt)
        upgrading_contract = (
            (
                job["kind"] == "extract"
                and context.get("relation_task")
                not in {"bill_lineage", "bill_policy", "ex_officio_chair"}
                and context.get("output_contract") != DIRECTIONAL_CONTRACT
            )
            or (
                job["kind"] == "community"
                and context.get("output_contract") != SELECTION_CONTRACT
                and context.get("output_contract") != target_contract
            )
            or (
                job["kind"] in {"query_local", "query_map", "query_reduce"}
                and context.get("output_contract")
                not in {
                    ANSWER_CONTRACT,
                    LEGACY_ANSWER_CONTRACT,
                    CLAIM_SELECTION_CONTRACT,
                    SOURCE_GROUP_SELECTION_CONTRACT,
                }
            )
        )
        delay = (
            0
            if attempt == 1 or upgrading_contract
            else min(3600, 30 * 2 ** min(attempt - 2, 7))
        )
        if instant < job["updated_at"] + delay:
            continue
        key = (
            fingerprint([job["key"], OUTPUT_CONTRACT])
            if attempt == 1
            and context.get("output_contract") is None
            and job["kind"] in {"extract", "community"}
            else fingerprint([job["key"], RETRY_VERSION, attempt])
        )
        if (job["kind"], key) in known:
            continue
        planned.append(
            {
                "kind": job["kind"],
                "key": key,
                "request": _next_request(job, attempt),
                "context": {
                    **context,
                    "output_contract": target_contract,
                    "retry_of": job["id"],
                    "retry_attempt": attempt,
                },
            }
        )
        if len(planned) >= room:
            break
    if planned:
        store.enqueue_many(planned)
    return len(planned)
