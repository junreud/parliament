"""Renew long-running local validation leases without changing remote identity."""

import math
from typing import TYPE_CHECKING

from parliament_worker.graphrag.job_codec import encode_job
from parliament_worker.graphrag.store_schema import (
    require_lease,
    store_clock,
    validate_label,
)

if TYPE_CHECKING:
    from parliament_worker.graphrag.store import GraphStore


def renew_leases(
    store: "GraphStore",
    owner: str,
    job_ids: list[str],
    lease_seconds: float,
    *,
    now: float | None = None,
) -> None:
    """Atomically extend only still-owned, nonexpired job leases.

    Args:
        store: Private durable job repository.
        owner: Current worker identity.
        job_ids: Remaining response jobs in the current HTTP wave.
        lease_seconds: New lease duration from the renewal instant.
        now: Optional deterministic clock for tests.

    Raises:
        ValueError: If any job has an expired or different-owner lease.
    """
    validate_label(owner)
    instant = store_clock(now)
    if (
        not math.isfinite(lease_seconds)
        or lease_seconds <= 0
        or len(job_ids) != len(set(job_ids))
    ):
        raise ValueError("invalid graph lease renewal")
    if not job_ids:
        return
    with store._transaction() as db:
        for job_id in job_ids:
            job = require_lease(store._read_job(db, job_id), owner, instant)
            job["lease_until"] = instant + lease_seconds
            db.execute(
                "UPDATE jobs SET data=? WHERE id=?",
                (encode_job(job), job_id),
            )
