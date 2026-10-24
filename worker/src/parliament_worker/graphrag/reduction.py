"""Bounded global reductions preserve explicit claim-to-evidence associations."""

from typing import Any

from parliament_worker.graphrag.answer_quality import editorial_reasons
from parliament_worker.graphrag.claim_selection import (
    REQUESTED_FACETS,
    selection_batches,
    selection_request,
)
from parliament_worker.graphrag.inputs import fingerprint
from parliament_worker.graphrag.query import (
    _answer_request,
    compact_question_dependency,
)
from parliament_worker.graphrag.question_jobs import latest_question_jobs
from parliament_worker.graphrag.source_safety import contains_contact
from parliament_worker.graphrag.store import GraphStore


def paired_context(
    points: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Deduplicate proof storage without dropping different claims sharing it."""
    unique = {fingerprint(point["evidence"]): point["evidence"] for point in points}
    aliases = {key: f"S{index + 1}" for index, key in enumerate(unique)}
    return list(unique.values()), [
        {"summary": point["text"], "unit": aliases[fingerprint(point["evidence"])]}
        for point in points
    ]


def _batches(question: str, points: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    batches, current = [], []
    for point in points:
        candidate = current + [point]
        proofs, context = paired_context(candidate)
        try:
            _answer_request(question, proofs, context_text=context)
        except ValueError:
            if not current:
                raise
            batches.append(current)
            current = [point]
        else:
            current = candidate
    if current:
        batches.append(current)
    return batches


def _source_facets(sources: list[dict[str, Any]]) -> dict[str, str]:
    """Label official document kinds without inferring a person's action."""
    labels: dict[str, str] = {}
    ambiguous: set[str] = set()
    for source in sources:
        document = source["payload"]["document"]
        url = document.get("sourceUrl")
        kind = document.get("sourceKey")
        title = document.get("title", "")
        if not isinstance(url, str) or not url:
            continue
        if kind in {"lawmaking-bill-detail", "lawmaking-bill-attachment"}:
            facet = "alternative_bill" if "대안" in title else "original_bill"
        elif kind == "ministry-press-release":
            facet = "government_followup"
        else:
            continue
        if url in labels and labels[url] != facet:
            ambiguous.add(url)
        labels[url] = facet
    return {url: facet for url, facet in labels.items() if url not in ambiguous}


def plan_reductions(store: GraphStore) -> int:
    """Reduce only complete map rounds, preserving all inputs across bounded batches."""
    planned = 0
    for question in store.artifacts("question"):
        payload = question["payload"]
        if (
            store.get_artifact("answer", question["key"])
            or payload["mode"] != "global"
            or payload["state"] != "queued"
            or not payload["jobs"]
        ):
            continue
        jobs = latest_question_jobs(store, payload["jobs"])
        if any(job is None or job["state"] != "completed" for job in jobs):
            continue
        source_facets = _source_facets(store.sources())
        points = {}
        for job in jobs:
            for claim in job["result"]["claims"]:
                proof = claim.get("evidence", {})
                facet = source_facets.get(proof.get("sourceUrl"))
                if (
                    not editorial_reasons(claim, facet)
                    and not contains_contact(claim["text"])
                    and not contains_contact(proof["text"])
                ):
                    points[fingerprint(claim)] = claim
        if not points:
            store.put_artifact(
                "question",
                question["key"],
                question["dependency"],
                {
                    **payload,
                    "state": "insufficient_evidence",
                    "claims": [],
                    "answer": "",
                },
            )
            continue
        try:
            batches = _batches(payload["question"], list(points.values()))
        except ValueError:
            batches = []
        # Full-proof rounds that barely shrink would exhaust the bounded
        # reduction depth. Select pinned claim IDs without rewriting facts.
        available_facets = {
            source_facets.get(point["evidence"].get("sourceUrl"))
            for point in points.values()
        }
        requested_facets = {
            facet
            for facet, phrases in REQUESTED_FACETS
            if facet in available_facets
            and any(phrase in payload["question"] for phrase in phrases)
        }
        use_selection = (
            len(requested_facets) >= 2
            or not batches
            or (len(jobs) > 1 and len(batches) > len(jobs) // 2)
        )
        if use_selection:
            try:
                batches = selection_batches(
                    payload["question"],
                    list(points.values()),
                    source_facets=source_facets,
                )
            except ValueError:
                batches = []
        if (
            not batches
            or payload.get("reductionRound", 0) >= 8
            or (len(batches) >= len(jobs) and len(batches) > 1)
        ):
            store.put_artifact(
                "question",
                question["key"],
                question["dependency"],
                {
                    **payload,
                    "state": "context_limit",
                    "error": "global_reduce_cannot_contract",
                },
            )
            continue
        requests = []
        job_dependency = compact_question_dependency(question["dependency"])
        for index, batch in enumerate(batches):
            if use_selection:
                body, proof_context = selection_request(
                    payload["question"], batch, source_facets=source_facets
                )
            else:
                proofs, context = paired_context(batch)
                body, proof_context = _answer_request(
                    payload["question"], proofs, context_text=context
                )
            final = len(batches) == 1
            requests.append(
                {
                    "kind": "query_reduce" if final else "query_map",
                    "key": fingerprint(
                        [question["key"], payload["jobs"], index]
                        + (["selection-v1"] if use_selection else [])
                    ),
                    "request": body,
                    "context": {
                        **job_dependency,
                        **proof_context,
                        "artifact_key": (
                            question["key"]
                            if final
                            else (
                                question["key"]
                                + ":reduce:"
                                + str(payload.get("reductionRound", 0) + 1)
                                + ":"
                                + str(index)
                            )
                        ),
                        "question_id": question["key"],
                    },
                }
            )
        identifiers = store.enqueue_many(requests)
        store.put_artifact(
            "question",
            question["key"],
            question["dependency"],
            {
                **payload,
                "jobs": identifiers,
                "reductionRound": payload.get("reductionRound", 0) + 1,
                "reductionMode": (
                    "claim_selection" if use_selection else "full_evidence"
                ),
            },
        )
        planned += len(identifiers)
    return planned
