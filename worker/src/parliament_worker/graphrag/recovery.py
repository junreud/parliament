"""Keep unobserved acceptance private until its original request is resolved."""

import time
from typing import Any

from parliament_worker.graphrag.store import GraphStore


def pause_unknown_acceptance(store: GraphStore, job_id: str, now: float) -> None:
    """Pause submission without cancelling or replacing the original request."""
    store.put_artifact(
        "control",
        "pause",
        {},
        {"reason": "inference_acceptance_unknown", "jobId": job_id, "at": now},
    )


def defer_unknown_acceptance(
    store: GraphStore, job: dict[str, Any], owner: str, now: float
) -> bool:
    """Block automatic resubmission until the existing remote request is found.

    Args:
        store: Private durable factory state.
        job: Leased request with its original body and idempotency key.
        owner: Current lease holder.
        now: Current Unix timestamp.

    Returns:
        True when acceptance is unresolved and the request must stay deferred.
    """
    if job["remote_id"] or not job["metadata"].get("completion_uncertain"):
        return False
    store.release(
        job["id"],
        owner,
        state="deferred",
        next_poll=now + 3600,
        error="inference_acceptance_unknown",
    )
    pause_unknown_acceptance(store, job["id"], now)
    return True


def recover_unknown_acceptance(store: GraphStore, client: Any, signature: str) -> bool:
    """Resume every uncertain submission through its original idempotency key.

    Args:
        store: Durable request and pause state.
        client: Inference client with ready and submit operations.
        signature: Configured actual model repository and revision.

    Returns:
        True only when the remote ID is durably recorded and the pause cleared.
    """
    pause = store.get_artifact("control", "pause")
    if pause and pause["payload"].get("reason") != "inference_acceptance_unknown":
        return False
    uncertain = [
        job
        for job in store.jobs(state="deferred")
        if not job["remote_id"]
        and job["metadata"].get("completion_uncertain")
        and job["metadata"].get("expected_model") == signature
        and not (job["lease_owner"] and job["lease_until"] > time.time())
    ]
    job_id = pause["payload"].get("jobId") if pause else None
    job = next((item for item in uncertain if item["id"] == job_id), None)
    if pause and job is None:
        prior = store.get_job(job_id) if isinstance(job_id, str) else None
        if prior and prior["remote_id"] and prior["state"] == "polling":
            store.invalidate_artifact("control", "pause")
            if uncertain:
                pause_unknown_acceptance(store, uncertain[0]["id"], time.time())
            return True
        return False
    if job is None:
        job = uncertain[0] if uncertain else None
    if job is None:
        return False
    ready = client.ready()
    repository = ready.get("model_repository")
    revision = ready.get("model_revision")
    if (
        ready.get("ready") is not True
        or not isinstance(repository, str)
        or not isinstance(revision, str)
        or repository + "@" + revision != signature
    ):
        return False
    if not pause:
        pause_unknown_acceptance(store, job["id"], time.time())
    response = client.submit(job["request"], job["idempotency_key"])
    remote_id = response["request_id"]
    metadata = {k: v for k, v in job["metadata"].items() if k != "error_status"}
    metadata["completion_uncertain"] = False
    store.update_job(
        job["id"],
        state="polling",
        remote_id=remote_id,
        next_poll=time.time(),
        metadata=metadata,
        error=None,
    )
    store.invalidate_artifact("control", "pause")
    remaining = next((item for item in uncertain if item["id"] != job["id"]), None)
    if remaining:
        pause_unknown_acceptance(store, remaining["id"], time.time())
    return True


def drain_unknown_acceptance(
    store: GraphStore, client: Any, signature: str, *, limit: int
) -> int:
    """Recover a bounded backlog before normal graph planning resumes.

    Args:
        store: Durable private requests and remote identities.
        client: Provider client that enforces the original idempotency key.
        signature: Pinned model repository and revision.
        limit: Maximum original requests to recover in one operator pass.

    Returns:
        Number of original requests whose remote IDs were saved.
    """
    if not 1 <= limit <= 64:
        raise ValueError("invalid acceptance recovery limit")
    recovered = 0
    while recovered < limit and recover_unknown_acceptance(store, client, signature):
        recovered += 1
    return recovered
