"""Private question result readback and source collection metadata."""

from typing import Any

from parliament_worker.graphrag.answer_temporal import (
    CURRENT_TENURE_QUESTION,
    OBSERVATION_TIME_QUESTION,
)
from parliament_worker.graphrag.index import dependencies_current
from parliament_worker.graphrag.store import GraphStore


def question_status(store: GraphStore, identifier: str) -> dict[str, Any] | None:
    """Expose fixed-source results and explicit partial, obsolete or failure states."""
    from parliament_worker.graphrag.query import _snapshot

    question = store.get_artifact("question", identifier)
    if question is None:
        return None
    payload = dict(question["payload"])
    payload["outdatedIndex"] = payload["snapshot"] != _snapshot(store)
    sources = {source["scope"]: source for source in store.sources()}
    if not dependencies_current(question["dependency"], sources):
        payload.update(state="obsolete", error="source_changed")
        return payload
    prompt = payload.get("question", "")
    if (
        payload.get("mode") == "local"
        and isinstance(prompt, str)
        and (
            CURRENT_TENURE_QUESTION.search(prompt)
            or OBSERVATION_TIME_QUESTION.search(prompt)
        )
    ):
        documents: set[str] = set()
        for job_id in payload.get("jobs", []):
            job = store.get_job(job_id)
            if job is None or job["kind"] != "query_local":
                continue
            for unit in job["context"].get("units", {}).values():
                if isinstance(unit, dict) and isinstance(unit.get("documentId"), str):
                    documents.add(unit["documentId"])
        payload["sourceObservations"] = store.source_observations_for_documents(
            documents
        )
    final = store.get_artifact("answer", identifier)
    if final:
        payload.update(
            final["payload"],
            state=(
                "insufficient_evidence"
                if final["payload"].get("insufficient") is True
                else "completed"
            ),
        )
    elif payload.get("jobs"):
        from parliament_worker.graphrag import question_jobs

        jobs = question_jobs.latest_question_jobs(store, payload["jobs"])
        terminal = question_jobs.terminal_question_result(
            jobs, payload["outdatedIndex"]
        )
        if terminal:
            payload.update(terminal)
        else:
            payload["progress"] = {
                "completed": sum(job and job["state"] == "completed" for job in jobs),
                "total": len(jobs),
            }
    payload.pop("jobs", None)
    return payload
