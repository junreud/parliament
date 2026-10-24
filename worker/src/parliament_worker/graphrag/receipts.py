"""Durably record a whole HTTP wave before validating any completed contents."""

import time
from typing import TYPE_CHECKING, Any

from parliament_worker.graphrag.client import InferenceError

if TYPE_CHECKING:
    from parliament_worker.graphrag.engine import Factory


def save_receipts(
    factory: "Factory", responses: list[tuple[dict[str, Any], dict[str, Any]]]
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Commit receipts atomically; completed jobs retain their validation leases.

    Args:
        factory: The single durable-state coordinator.
        responses: Decoded, transport-validated responses in arrival order.

    Returns:
        Completed jobs with durable remote IDs, ready for local validation.
    """
    now = time.time()
    changes, completed = [], []
    for job, response in responses:
        state = response.get("state")
        if state not in {
            "received",
            "queued",
            "running",
            "completed",
            "failed",
            "cancelled",
        }:
            raise InferenceError(
                "unrecognized_remote_state", retryable=True, uncertain=True
            )
        metadata = {
            **job["metadata"],
            **response.get("_modelMetadata", {}),
            "completion_uncertain": False,
        }
        fields = {
            "remote_id": response.get("request_id") or job["remote_id"],
            "metadata": metadata,
        }
        if state in {"received", "queued", "running"}:
            fields.update(
                state="polling", next_poll=now + factory.poll_seconds, error=None
            )
        elif state in {"failed", "cancelled"}:
            fields.update(state="failed", error="remote_inference_failed")
        else:
            completed.append(({**job, **fields}, response))
        changes.append((job["id"], fields, state != "completed"))
    if changes:
        factory.store.update_leased(factory.owner, changes)
    return completed
