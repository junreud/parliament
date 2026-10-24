"""Summarize current logical work separately from immutable retry history."""

import sqlite3
from collections import defaultdict
from typing import Any

from parliament_worker.graphrag.store_schema import STATES


def summarize_latest(
    jobs: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, int]], int]:
    """Count only the newest attempt for each derivation target.

    Args:
        jobs: Persisted jobs in insertion order, including historical attempts.

    Returns:
        Per-kind current-state counts and the number of unresolved failures.
    """
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for job in jobs:
        key = job["context"].get("artifact_key")
        if isinstance(key, str):
            latest[(job["kind"], key)] = job
    counts: dict[str, dict[str, int]] = defaultdict(
        lambda: dict.fromkeys(sorted(STATES), 0)
    )
    for (kind, _), job in latest.items():
        counts[kind][job["state"]] += 1
    return dict(counts), sum(job["state"] == "failed" for job in latest.values())


def failed_keys_pending_recovery(jobs: list[dict[str, Any]]) -> int:
    """Count failed derivations whose newest attempt has not succeeded.

    Args:
        jobs: Persisted attempts in insertion order.

    Returns:
        Number of distinct failed derivations awaiting a successful retry.
    """
    failed: set[tuple[str, str]] = set()
    latest: dict[tuple[str, str], str] = {}
    for job in jobs:
        key = job["context"].get("artifact_key")
        if not isinstance(key, str):
            continue
        logical = (job["kind"], key)
        latest[logical] = job["state"]
        if job["state"] == "failed":
            failed.add(logical)
    return sum(latest[key] not in {"completed", "obsolete"} for key in failed)


def status_from_db(db: sqlite3.Connection) -> dict[str, Any]:
    """Read sanitized operational counts from one consistent database snapshot."""
    jobs = [
        {
            "kind": row["kind"],
            "state": row["job_state"],
            "context": {"artifact_key": row["artifact_key"]},
        }
        for row in db.execute(
            "SELECT kind, json_extract(data, '$.state') AS job_state, "
            "json_extract(data, '$.context.artifact_key') AS artifact_key "
            "FROM jobs ORDER BY rowid"
        )
    ]
    historical = dict.fromkeys(sorted(STATES), 0)
    for job in jobs:
        historical[job["state"]] += 1
    latest, unresolved = summarize_latest(jobs)
    return {
        "jobs": historical,
        "latest_jobs": latest,
        "unresolved_failures": unresolved,
        "failed_keys_pending_recovery": failed_keys_pending_recovery(jobs),
        "active_sources": db.execute(
            "SELECT COUNT(*) FROM sources WHERE active=1"
        ).fetchone()[0],
        "observations": db.execute("SELECT COUNT(*) FROM observations").fetchone()[0],
        "current_artifacts": db.execute(
            "SELECT COUNT(*) FROM artifacts WHERE current=1"
        ).fetchone()[0],
    }
