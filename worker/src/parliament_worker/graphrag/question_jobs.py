"""Resolve question work to its newest durable attempt in one database read."""

from typing import TYPE_CHECKING, Any

from parliament_worker.graphrag.job_codec import decode_job

if TYPE_CHECKING:
    from parliament_worker.graphrag.store import GraphStore


def latest_question_jobs(
    store: "GraphStore", identifiers: list[str]
) -> list[dict[str, Any] | None]:
    """Find current attempts for the question jobs originally recorded.

    Args:
        store: Private durable GraphRAG state.
        identifiers: Original job IDs saved on the question artifact.

    Returns:
        Jobs in the same order, replacing failed attempts with their latest
        retry for the same question, kind, and output artifact key.
    """
    if not identifiers:
        return []
    wanted = set(identifiers)
    by_id: dict[str, dict[str, Any]] = {}
    latest: dict[tuple[str, str, str], dict[str, Any]] = {}
    with store._transaction(write=False) as db:
        for row in db.execute(
            "SELECT data FROM jobs WHERE kind IN "
            "('query_local','query_map','query_reduce') ORDER BY rowid"
        ):
            job = decode_job(row["data"])
            context = job["context"]
            question_id = context.get("question_id")
            artifact_key = context.get("artifact_key")
            if isinstance(question_id, str) and isinstance(artifact_key, str):
                latest[(question_id, job["kind"], artifact_key)] = job
            if job["id"] in wanted:
                by_id[job["id"]] = job
    resolved = []
    for identifier in identifiers:
        original = by_id.get(identifier)
        if original is None:
            resolved.append(None)
            continue
        context = original["context"]
        resolved.append(
            latest.get(
                (
                    context.get("question_id"),
                    original["kind"],
                    context.get("artifact_key"),
                ),
                original,
            )
        )
    return resolved


def terminal_question_result(
    jobs: list[dict[str, Any] | None], outdated_index: bool
) -> dict[str, str] | None:
    """Separate obsolete question work from an actual inference failure.

    Args:
        jobs: Latest durable attempts for one question.
        outdated_index: Whether the source and report snapshot has changed.

    Returns:
        A terminal state and reason, or None while work can still finish.
    """
    states = {job["state"] for job in jobs if job}
    if "failed" in states:
        return {"state": "failed", "error": "inference_or_source_validation_failed"}
    if "obsolete" in states:
        return {
            "state": "obsolete",
            "error": "index_changed" if outdated_index else "job_obsolete",
        }
    return None
