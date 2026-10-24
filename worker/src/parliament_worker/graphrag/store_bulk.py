"""Batch graph retirement decisions into one private database snapshot write."""

import time
from typing import TYPE_CHECKING

from parliament_worker.graphrag.job_codec import encode_job
from parliament_worker.graphrag.store_schema import updated_job, validate_label

if TYPE_CHECKING:
    from parliament_worker.graphrag.store import GraphStore


def stored_artifact_versions(store: "GraphStore") -> set[tuple[str, str, str]]:
    """Read version identities without loading historical payloads into memory."""
    with store._transaction(write=False) as db:
        return {
            (row["kind"], row["artifact_key"], row["version"])
            for row in db.execute("SELECT kind, artifact_key, version FROM artifacts")
        }


def retire_results(
    store: "GraphStore",
    artifacts: list[tuple[str, str]],
    jobs: list[str] | None = None,
) -> int:
    """Withdraw stale results without deleting versions or changing leased jobs.

    Args:
        store: Private graph repository.
        artifacts: Artifact family and logical key pairs to withdraw.
        jobs: Job IDs to mark obsolete when their lease permits it.

    Returns:
        Number of current artifacts and jobs actually retired.
    """
    targets = list(dict.fromkeys(artifacts))
    job_ids = list(dict.fromkeys(jobs or []))
    for kind, key in targets:
        validate_label(kind)
        validate_label(key)
    for job_id in job_ids:
        validate_label(job_id)
    if not targets and not job_ids:
        return 0
    retired = 0
    with store._transaction() as db:
        for kind, key in targets:
            result = db.execute(
                "UPDATE artifacts SET current=0 WHERE kind=? AND artifact_key=? AND current=1",
                (kind, key),
            )
            retired += result.rowcount
        now = time.time()
        for job_id in job_ids:
            job = store._read_job(db, job_id)
            if job is None or job["state"] == "obsolete":
                continue
            if job["lease_owner"] and job["lease_until"] > now:
                continue
            successor = updated_job(job, {"state": "obsolete"}, now)
            db.execute(
                "UPDATE jobs SET data=? WHERE id=?",
                (encode_job(successor), job_id),
            )
            retired += 1
    return retired
