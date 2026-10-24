"""SQLite schema and state transitions for private GraphRAG storage."""

import json
import math
import time
from hashlib import sha256
from typing import Any

# Rebuilding the report-key-scoped hierarchy and its global question preserves
# prior attempts, exceeding the former 1.024 GB ceiling. Keep a bounded ceiling
# until disk-backed storage replaces whole-file snapshots.
MAX_SNAPSHOT_BYTES = 1_536_000_000
STATES = set("planned submitting polling completed failed obsolete deferred".split())
RUNNABLE = {"planned", "submitting", "polling", "deferred"}
TRANSITIONS = {
    "planned": {"submitting", "deferred", "failed", "obsolete"},
    "deferred": {"planned", "submitting", "polling", "completed", "failed", "obsolete"},
    "submitting": {"polling", "completed", "deferred", "failed", "obsolete"},
    "polling": {"completed", "deferred", "failed", "obsolete"},
    "completed": {"obsolete"},
    "failed": {"obsolete"},
    "obsolete": set(),
}
UPDATE_FIELDS = set("state remote_id next_poll attempts result error metadata".split())
JOB_PRIORITIES = {
    "query_reduce": 0,
    "query_local": 0,
    "query_map": 1,
    "extract": 2,
    "community": 3,
}
SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    scope TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, generation INTEGER NOT NULL,
    payload TEXT NOT NULL, active INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS source_versions (scope TEXT NOT NULL,
    fingerprint TEXT NOT NULL, payload TEXT NOT NULL,
    PRIMARY KEY(scope, fingerprint));
CREATE TABLE IF NOT EXISTS observations (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT NOT NULL,
    fingerprint TEXT NOT NULL, generation INTEGER NOT NULL,
    active INTEGER NOT NULL, observed_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS source_observation_times (
    scope TEXT NOT NULL, fingerprint TEXT NOT NULL,
    generation INTEGER NOT NULL, first_observed_at TEXT NOT NULL,
    last_observed_at TEXT NOT NULL,
    PRIMARY KEY(scope, fingerprint, generation));
CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, kind TEXT NOT NULL, task_key TEXT NOT NULL,
    data TEXT NOT NULL, UNIQUE(kind, task_key));
CREATE TABLE IF NOT EXISTS artifacts (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
    artifact_key TEXT NOT NULL, version TEXT NOT NULL, dependency TEXT NOT NULL,
    payload TEXT NOT NULL, current INTEGER NOT NULL,
    UNIQUE(kind, artifact_key, version));
CREATE INDEX IF NOT EXISTS artifact_current ON artifacts(kind, current);
"""


def canonical_json(value: Any) -> str:
    """Encode exact JSON semantics for immutable request and artifact comparisons."""
    options = {"ensure_ascii": False, "sort_keys": True, "allow_nan": False}
    return json.dumps(value, separators=(",", ":"), **options)


def content_digest(value: Any) -> str:
    """Hash canonical UTF-8 JSON instead of mutable dictionary insertion order."""
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def validate_label(value: str) -> None:
    """Reject empty, oversized, or NUL-bearing logical identifiers."""
    if not isinstance(value, str) or not value or len(value) > 4096 or "\x00" in value:
        raise ValueError("invalid store identifier")


def store_clock(now: float | None) -> float:
    """Return a finite epoch time for scheduling and ownership checks."""
    value = time.time() if now is None else float(now)
    if not math.isfinite(value) or value < 0:
        raise ValueError("invalid store clock")
    return value


def reject_credentials(value: Any) -> None:
    """Keep authentication values out of persisted requests and model metadata."""
    forbidden = set(
        "authorization apikey accesstoken inferencetoken factorytoken".split()
    )
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower().replace("_", "").replace("-", "")
            if normalized in forbidden:
                raise ValueError("credentials must not be persisted in graph jobs")
            reject_credentials(item)
    elif isinstance(value, list):
        for item in value:
            reject_credentials(item)


def job_priority(job: dict[str, Any]) -> tuple[int, int, int]:
    """Serve remote recovery first, then untried peers before repeat attempts."""
    recovery_rank = 0 if job["remote_id"] else 1 if job["state"] == "submitting" else 2
    priority = JOB_PRIORITIES.get(job["kind"], 3)
    if isinstance(job["context"].get("retry_of"), str) or isinstance(
        job["context"].get("repair_version"), str
    ):
        priority = min(priority, 0 if job["kind"] == "query_map" else 1)
    return (recovery_rank, priority, job["attempts"])


def require_lease(job: dict[str, Any] | None, owner: str, now: float) -> dict[str, Any]:
    """Refuse a missing, expired, or different-owner durable lease."""
    if job is None or job["lease_owner"] != owner or job["lease_until"] <= now:
        raise ValueError("stale graph job lease")
    return job


def updated_job(
    job: dict[str, Any], fields: dict[str, Any], now: float
) -> dict[str, Any]:
    """Validate mutable fields while retaining request/result and remote-ID contracts."""
    if set(fields) - UPDATE_FIELDS:
        raise ValueError("immutable or unknown job field")
    state = fields.get("state", job["state"])
    if state not in STATES or (
        state != job["state"] and state not in TRANSITIONS[job["state"]]
    ):
        raise ValueError("invalid job transition")
    if job["state"] in {"completed", "obsolete"}:
        if any(key != "state" and value != job[key] for key, value in fields.items()):
            raise ValueError("completed job is immutable")
    if (
        job["remote_id"] is not None
        and "remote_id" in fields
        and fields["remote_id"] != job["remote_id"]
    ):
        raise ValueError("remote request identity is immutable")
    if "attempts" in fields and (
        not isinstance(fields["attempts"], int)
        or isinstance(fields["attempts"], bool)
        or fields["attempts"] < job["attempts"]
    ):
        raise ValueError("invalid job attempt count")
    if "next_poll" in fields:
        store_clock(fields["next_poll"])
    if state == "polling" and not fields.get("remote_id", job["remote_id"]):
        raise ValueError("polling requires remote request identity")
    if state == "completed" and fields.get("result", job["result"]) is None:
        raise ValueError("completion requires a persisted result")
    reject_credentials(fields)
    return {**job, **fields, "updated_at": now}
