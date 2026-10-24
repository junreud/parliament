"""Durable private GraphRAG revisions and resumable inference work."""

import json
import math
import os
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from parliament_worker.graphrag.job_codec import decode_job, encode_job
from parliament_worker.graphrag.source_observations import SourceObservationMixin
from parliament_worker.graphrag.status import status_from_db
from parliament_worker.graphrag.store_queries import query_snapshot
from parliament_worker.graphrag.store_schema import (
    MAX_SNAPSHOT_BYTES,
    RUNNABLE,
    STATES,
)
from parliament_worker.graphrag.store_schema import canonical_json as _json
from parliament_worker.graphrag.store_schema import content_digest as _digest
from parliament_worker.graphrag.store_schema import job_priority
from parliament_worker.graphrag.store_schema import (
    reject_credentials as _reject_credentials,
)
from parliament_worker.graphrag.store_schema import require_lease
from parliament_worker.graphrag.store_schema import store_clock as _clock
from parliament_worker.graphrag.store_schema import updated_job
from parliament_worker.graphrag.store_schema import validate_label as _label
from parliament_worker.graphrag.store_sources import source_row
from parliament_worker.graphrag.store_transactions import (
    BatchState,
    database_transaction,
)
from parliament_worker.knowledge.files import private_write


class GraphStore(SourceObservationMixin):
    """Persist short, independently locked transactions without holding HTTP locks.

    Args:
        root: Private storage directory; user-created symlinks are refused.
    """

    def __init__(self, root: Path) -> None:
        self.root = root.absolute()
        for alias in (Path("/tmp"), Path("/var")):
            if self.root.is_relative_to(alias):
                self.root = alias.resolve() / self.root.relative_to(alias)
        private_write(self.root / ".boundary", b"parliament-graphrag-v1\n")
        os.chmod(self.root, 0o700, follow_symlinks=False)
        self.database = self.root / "graph.sqlite3"
        self._batch = BatchState()
        with self._transaction():
            pass

    @contextmanager
    def _transaction(self, *, write: bool = True) -> Iterator[sqlite3.Connection]:
        if self._batch.current() is not None:
            with self._batch.nested(write=write) as connection:
                yield connection
            return
        with database_transaction(
            self.root,
            self.database,
            write=write,
            max_snapshot_bytes=MAX_SNAPSHOT_BYTES,
        ) as connection:
            yield connection

    @contextmanager
    def batch(self) -> Iterator[None]:
        """Commit a bounded wave of store calls in one atomic snapshot."""
        with self._transaction() as connection:
            with self._batch.bind(connection):
                yield

    def close(self) -> None:
        """No-op; every operation has already released its database lock."""

    def put_source(self, scope: str, fingerprint: str, payload: dict[str, Any]) -> bool:
        """Append a revision, preserving A→B→A and rejecting hash collisions."""
        with self._transaction() as db:
            return self._put_source(db, scope, fingerprint, payload)

    def put_sources(self, items: list[dict[str, Any]]) -> int:
        """Atomically load a source batch with one snapshot write.

        Args:
            items: Source scope, fingerprint and payload dictionaries.

        Returns:
            Number of actual source transitions in the committed batch.
        """
        with self._transaction() as db:
            changed = 0
            for item in items:
                changed += self._put_source(
                    db, item["scope"], item["fingerprint"], item["payload"]
                )
                self._record_source_observation(db, item)
            return changed

    @staticmethod
    def _put_source(
        db: sqlite3.Connection, scope: str, fingerprint: str, payload: dict[str, Any]
    ) -> bool:
        _label(scope)
        _label(fingerprint)
        encoded = _json(payload)
        prior = db.execute("SELECT * FROM sources WHERE scope=?", (scope,)).fetchone()
        version = db.execute(
            "SELECT payload FROM source_versions WHERE scope=? AND fingerprint=?",
            (scope, fingerprint),
        ).fetchone()
        if version and version["payload"] != encoded:
            raise ValueError("immutable source version conflict")
        if prior and prior["active"] and prior["fingerprint"] == fingerprint:
            return False
        generation = prior["generation"] + 1 if prior else 1
        db.execute(
            "INSERT OR IGNORE INTO source_versions VALUES(?,?,?)",
            (scope, fingerprint, encoded),
        )
        db.execute(
            "INSERT OR REPLACE INTO sources VALUES(?,?,?,?,1)",
            (scope, fingerprint, generation, encoded),
        )
        db.execute(
            "INSERT INTO observations(scope,fingerprint,generation,active,observed_at) VALUES(?,?,?,1,?)",
            (scope, fingerprint, generation, time.time()),
        )
        return True

    def retire_source(self, scope: str) -> bool:
        """Deactivate a source while retaining its original versions and history."""
        with self._transaction() as db:
            prior = db.execute(
                "SELECT * FROM sources WHERE scope=?", (scope,)
            ).fetchone()
            if not prior or not prior["active"]:
                return False
            generation = prior["generation"] + 1
            db.execute(
                "UPDATE sources SET active=0,generation=? WHERE scope=?",
                (generation, scope),
            )
            db.execute(
                "INSERT INTO observations(scope,fingerprint,generation,active,observed_at) VALUES(?,?,?,0,?)",
                (scope, prior["fingerprint"], generation, time.time()),
            )
        return True

    def sources(
        self, *, active_only: bool = True, include_payload: bool = True
    ) -> list[dict[str, Any]]:
        """Read current revisions, optionally without restoring source bodies."""
        columns = "*" if include_payload else "scope,fingerprint,generation,active"
        with self._transaction(write=False) as db:
            rows = db.execute(
                f"SELECT {columns} FROM sources"
                + (" WHERE active=1" if active_only else "")
                + " ORDER BY scope"
            ).fetchall()
            return [source_row(row) for row in rows]

    def source_current(
        self, scope: str, fingerprint: str, generation: int | None = None
    ) -> bool:
        """Check a dependency, including its generation when recurrence matters."""
        with self._transaction(write=False) as db:
            row = db.execute("SELECT * FROM sources WHERE scope=?", (scope,)).fetchone()
            return bool(
                row
                and row["active"]
                and row["fingerprint"] == fingerprint
                and (generation is None or row["generation"] == generation)
            )

    def observations(self) -> list[dict[str, Any]]:
        """Return chronological source transitions without their document contents."""
        with self._transaction(write=False) as db:
            return [
                {**dict(row), "active": bool(row["active"])}
                for row in db.execute("SELECT * FROM observations ORDER BY sequence")
            ]

    def enqueue(
        self, kind: str, key: str, request: dict[str, Any], context: dict[str, Any]
    ) -> str:
        """Persist exact request bytes and a stable idempotency key before HTTP."""
        with self._transaction() as db:
            return self._enqueue(db, kind, key, request, context)

    def enqueue_many(self, items: list[dict[str, Any]]) -> list[str]:
        """Atomically persist kind/key/request/context jobs with one snapshot write."""
        with self._transaction() as db:
            return [
                self._enqueue(
                    db, item["kind"], item["key"], item["request"], item["context"]
                )
                for item in items
            ]

    @classmethod
    def _enqueue(
        cls,
        db: sqlite3.Connection,
        kind: str,
        key: str,
        request: dict[str, Any],
        context: dict[str, Any],
    ) -> str:
        _label(kind)
        _label(key)
        _reject_credentials(request)
        _reject_credentials(context)
        fingerprint = _digest([kind, key])
        job_id = "gr_" + fingerprint
        prior = cls._read_job(db, job_id)
        if prior:
            if _json(prior["request"]) != _json(request) or _json(
                prior["context"]
            ) != _json(context):
                raise ValueError("job replay conflict")
            return job_id
        now = time.time()
        job = {
            "id": job_id,
            "kind": kind,
            "key": key,
            "request": request,
            "context": context,
            "idempotency_key": "graphrag-" + fingerprint,
            "state": "planned",
            "remote_id": None,
            "next_poll": 0.0,
            "attempts": 0,
            "result": None,
            "error": None,
            "metadata": {},
            "lease_owner": None,
            "lease_until": 0.0,
            "created_at": now,
            "updated_at": now,
        }
        db.execute(
            "INSERT INTO jobs VALUES(?,?,?,?)", (job_id, kind, key, encode_job(job))
        )
        return job_id

    @staticmethod
    def _read_job(db: sqlite3.Connection, job_id: str) -> dict[str, Any] | None:
        row = db.execute("SELECT data FROM jobs WHERE id=?", (job_id,)).fetchone()
        return decode_job(row["data"]) if row else None

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        """Read a persisted job, including an uncertain remote submission."""
        with self._transaction(write=False) as db:
            return self._read_job(db, job_id)

    def jobs(
        self, state: str | None = None, kind: str | None = None
    ) -> list[dict[str, Any]]:
        """List work in insertion order, optionally filtering state and kind."""
        if state is not None and state not in STATES:
            raise ValueError("invalid job state")
        clauses: list[str] = []
        params: list[str] = []
        if kind is not None:
            clauses.append("kind=?")
            params.append(kind)
        if state is not None:
            clauses.append("json_extract(data, '$.state')=?")
            params.append(state)
        query = "SELECT data FROM jobs"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY rowid"
        with self._transaction(write=False) as db:
            return [decode_job(row["data"]) for row in db.execute(query, params)]

    @staticmethod
    def _runnable_jobs(db: sqlite3.Connection) -> list[dict[str, Any]]:
        """Decode only unfinished work while retaining insertion order."""
        states = tuple(sorted(RUNNABLE))
        placeholders = ",".join("?" for _ in states)
        rows = db.execute(
            "SELECT data FROM jobs WHERE json_extract(data, '$.state') IN ("
            + placeholders
            + ") ORDER BY rowid",
            states,
        )
        return [decode_job(row["data"]) for row in rows]

    @staticmethod
    def _due(job: dict[str, Any], now: float) -> bool:
        return (
            job["state"] in RUNNABLE
            and job["next_poll"] <= now
            and (not job["lease_owner"] or job["lease_until"] <= now)
        )

    def pending(
        self, limit: int = 100, now: float | None = None
    ) -> list[dict[str, Any]]:
        """Return runnable jobs without changing ownership."""
        if limit < 1 or limit > 10000:
            raise ValueError("invalid job limit")
        instant = _clock(now)
        with self._transaction(write=False) as db:
            ordered = sorted(self._runnable_jobs(db), key=job_priority)
        return [job for job in ordered if self._due(job, instant)][:limit]

    def update_job(self, job_id: str, **fields: Any) -> None:
        """Update an unleased job without changing its original request."""
        with self._transaction() as db:
            job = self._read_job(db, job_id)
            if job is None:
                raise ValueError("unknown graph job")
            now = time.time()
            if job["lease_owner"] and job["lease_until"] > now:
                raise ValueError("job has an active lease")
            updated = updated_job(job, fields, now)
            db.execute(
                "UPDATE jobs SET data=? WHERE id=?", (encode_job(updated), job_id)
            )

    def claim(
        self, owner: str, lease_seconds: float, limit: int = 1, now: float | None = None
    ) -> list[dict[str, Any]]:
        """Atomically lease due jobs; expired work can be safely resumed."""
        _label(owner)
        instant = _clock(now)
        if (
            not math.isfinite(lease_seconds)
            or lease_seconds <= 0
            or limit < 1
            or limit > 10000
        ):
            raise ValueError("invalid graph job lease")
        with self._transaction() as db:
            claimed = []
            jobs = sorted(self._runnable_jobs(db), key=job_priority)
            for job in jobs:
                if self._due(job, instant) and len(claimed) < limit:
                    job.update(
                        lease_owner=owner,
                        lease_until=instant + lease_seconds,
                        updated_at=instant,
                    )
                    db.execute(
                        "UPDATE jobs SET data=? WHERE id=?",
                        (encode_job(job), job["id"]),
                    )
                    claimed.append(job)
            return claimed

    def release(
        self, job_id: str, owner: str, *, now: float | None = None, **fields: Any
    ) -> None:
        """Commit work only for a still-valid lease owner, then release the lease."""
        self.update_leased(owner, [(job_id, fields, True)], now=now)

    def renew_leases(
        self,
        owner: str,
        job_ids: list[str],
        lease_seconds: float,
        *,
        now: float | None = None,
    ) -> None:
        """Extend still-owned leases during slow local result validation."""
        from parliament_worker.graphrag.store_leases import renew_leases

        renew_leases(self, owner, job_ids, lease_seconds, now=now)

    def checkpoint(
        self, job_id: str, owner: str, *, now: float | None = None, **fields: Any
    ) -> dict[str, Any]:
        """Persist pre-HTTP intent while retaining the original ownership lease."""
        return self.update_leased(owner, [(job_id, fields, False)], now=now)[0]

    def update_leased(
        self,
        owner: str,
        changes: list[tuple[str, dict[str, Any], bool]],
        *,
        now: float | None = None,
    ) -> list[dict[str, Any]]:
        """Atomically checkpoint or release a batch before any HTTP dispatch.

        Args:
            owner: Expected lease owner for every changed job.
            changes: Job ID, validated mutable fields, and release flag tuples.
            now: Optional epoch for checking all leases at the same instant.

        Returns:
            Updated jobs; no changes are saved if any lease or field is invalid.
        """
        instant = _clock(now)
        with self._transaction() as db:
            result = []
            for job_id, fields, release in changes:
                job = require_lease(self._read_job(db, job_id), owner, instant)
                updated = updated_job(job, fields, instant)
                if release:
                    updated.update(lease_owner=None, lease_until=0.0)
                db.execute(
                    "UPDATE jobs SET data=? WHERE id=?", (encode_job(updated), job_id)
                )
                result.append(updated)
            return result

    def put_artifact(
        self, kind: str, key: str, dependency: Any, payload: dict[str, Any]
    ) -> str:
        """Save an immutable derivation and atomically select its current version."""
        _label(kind)
        _label(key)
        version = _digest([kind, key, dependency, payload])
        with self._transaction() as db:
            prior = db.execute(
                "SELECT dependency,payload FROM artifacts WHERE kind=? AND artifact_key=? AND version=?",
                (kind, key, version),
            ).fetchone()
            if prior and (
                prior["dependency"] != _json(dependency)
                or prior["payload"] != _json(payload)
            ):
                raise ValueError("immutable artifact version conflict")
            db.execute(
                "UPDATE artifacts SET current=0 WHERE kind=? AND artifact_key=?",
                (kind, key),
            )
            db.execute(
                "INSERT INTO artifacts(kind,artifact_key,version,dependency,payload,current) VALUES(?,?,?,?,?,1) ON CONFLICT(kind,artifact_key,version) DO UPDATE SET current=1",
                (kind, key, version, _json(dependency), _json(payload)),
            )
        return version

    @staticmethod
    def _artifact(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "kind": row["kind"],
            "key": row["artifact_key"],
            "version": row["version"],
            "dependency": json.loads(row["dependency"]),
            "payload": json.loads(row["payload"]),
            "current": bool(row["current"]),
        }

    def get_artifact(self, kind: str, key: str) -> dict[str, Any] | None:
        """Return the current version only; invalidated revisions stay private."""
        with self._transaction(write=False) as db:
            row = db.execute(
                "SELECT * FROM artifacts WHERE kind=? AND artifact_key=? AND current=1 ORDER BY sequence DESC LIMIT 1",
                (kind, key),
            ).fetchone()
            return self._artifact(row) if row else None

    def artifacts(self, kind: str, current: bool = True) -> list[dict[str, Any]]:
        """Return current derivations, or their full immutable history."""
        with self._transaction(write=False) as db:
            rows = db.execute(
                "SELECT * FROM artifacts WHERE kind=?"
                + (" AND current=1" if current else "")
                + " ORDER BY sequence",
                (kind,),
            ).fetchall()
            return [self._artifact(row) for row in rows]

    def invalidate_artifact(self, kind: str, key: str) -> None:
        """Withdraw a derivation without deleting its version or citations."""
        with self._transaction() as db:
            db.execute(
                "UPDATE artifacts SET current=0 WHERE kind=? AND artifact_key=?",
                (kind, key),
            )

    def artifact_versions(self, kind: str, key: str) -> list[dict[str, Any]]:
        """Return every historical version for a logical artifact."""
        with self._transaction(write=False) as db:
            return [
                self._artifact(row)
                for row in db.execute(
                    "SELECT * FROM artifacts WHERE kind=? AND artifact_key=? ORDER BY sequence",
                    (kind, key),
                )
            ]

    def status(self) -> dict[str, Any]:
        """Return operational counts without prompts, document text, or credentials."""
        with self._transaction(write=False) as db:
            return status_from_db(db)

    def query_snapshot(self) -> dict[str, Any]:
        """Capture question inputs from one immutable database revision."""
        return query_snapshot(self)
