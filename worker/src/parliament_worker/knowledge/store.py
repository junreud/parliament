"""Private immutable raw/extraction storage with replay-safe observation history."""

import json
import re
import sqlite3
from contextlib import ExitStack
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from parliament_worker.knowledge.extract import digest
from parliament_worker.knowledge.files import (
    private_database_snapshot,
    private_read,
    private_write,
)


class PilotStore:
    """Keep content versions separate from chronological collection observations."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        database = self.root / "pilot.sqlite3"
        self._resources = ExitStack()
        try:
            snapshot = self._resources.enter_context(
                private_database_snapshot(database, root=self.root)
            )
            self.connection = sqlite3.connect(":memory:")
            self._resources.callback(self.connection.close)
            if not hasattr(self.connection, "serialize") or not hasattr(
                self.connection, "deserialize"
            ):
                raise RuntimeError("SQLite snapshot serialization support required")
            if snapshot:
                self.connection.deserialize(snapshot)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute(
                "CREATE TABLE IF NOT EXISTS observations (sequence INTEGER PRIMARY KEY AUTOINCREMENT, document_id TEXT NOT NULL, job_id TEXT NOT NULL, observation_id TEXT NOT NULL UNIQUE, payload_hash TEXT, status TEXT NOT NULL, changed INTEGER, error_category TEXT, observed_at TEXT NOT NULL, raw_key TEXT, spec_json TEXT NOT NULL, UNIQUE(document_id,job_id))"
            )
            self._commit()
        except Exception:
            self._resources.close()
            raise

    def _commit(self) -> None:
        """Commit in memory and atomically persist a normal restorable SQLite file."""
        self.connection.commit()
        private_write(
            self.root / "pilot.sqlite3",
            self.connection.serialize(),
            immutable=False,
            root=self.root,
        )

    def _existing(self, document_id: str, job_id: str) -> dict[str, Any] | None:
        """Read an exact observation and preserve its original collection time."""
        row = self.connection.execute(
            "SELECT * FROM observations WHERE document_id=? AND job_id=?",
            (document_id, job_id),
        ).fetchone()
        return self._wire(row) if row else None

    @staticmethod
    def _wire(row: sqlite3.Row) -> dict[str, Any]:
        """Return storage metadata without exposing absolute local paths."""
        return {
            "documentId": row["document_id"],
            "jobId": row["job_id"],
            "observationId": row["observation_id"],
            "version": row["payload_hash"],
            "status": row["status"],
            "changed": bool(row["changed"]) if row["changed"] is not None else None,
            "errorCategory": row["error_category"],
            "collectedAt": row["observed_at"],
            "observedAt": row["observed_at"],
            "rawStorageKey": row["raw_key"],
            "spec": json.loads(row["spec_json"]),
        }

    def observe(
        self, spec: dict[str, Any], raw: bytes, job_id: str, collected_at: datetime
    ) -> dict[str, Any]:
        """Append one successful job observation, including A→B→A recurrence.

        Args:
            spec: Validated source identity and extraction declaration.
            raw: Exact official response bytes.
            job_id: Stable ID reused only when retrying the same collection job.
            collected_at: Observation time; not a publication or occurrence date.

        Returns:
            First persisted observation for this document/job pair.
        """
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_id) or not raw:
            raise ValueError("invalid job or empty original")
        version = sha256(raw).hexdigest()
        existing = self._existing(spec["id"], job_id)
        if existing:
            if existing["version"] != version or existing["spec"] != spec:
                raise ValueError("job replay conflict")
            return existing
        key = f"raw/{digest([spec['sourceKey'], spec['recordKey']])}/{version}.bin"
        private_write(self.root / key, raw, root=self.root)
        last = self.connection.execute(
            "SELECT payload_hash FROM observations WHERE document_id=? AND status='success' ORDER BY sequence DESC LIMIT 1",
            (spec["id"],),
        ).fetchone()
        changed = last is None or last["payload_hash"] != version
        observation_id = "observation_" + digest([spec["id"], job_id])
        self.connection.execute(
            "INSERT INTO observations(document_id,job_id,observation_id,payload_hash,status,changed,observed_at,raw_key,spec_json) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                spec["id"],
                job_id,
                observation_id,
                version,
                "success",
                int(changed),
                collected_at.isoformat(),
                key,
                json.dumps(spec, ensure_ascii=False, sort_keys=True),
            ),
        )
        self._commit()
        return self._existing(spec["id"], job_id) or {}

    def failure(
        self, spec: dict[str, Any], job_id: str, observed_at: datetime, category: str
    ) -> None:
        """Record safe failure categories independently of an unchanged response."""
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_id):
            raise ValueError("invalid job")
        existing = self._existing(spec["id"], job_id)
        if existing:
            if existing["status"] != "failed":
                raise ValueError("job replay conflict")
            return
        self.connection.execute(
            "INSERT INTO observations(document_id,job_id,observation_id,status,error_category,observed_at,spec_json) VALUES(?,?,?,?,?,?,?)",
            (
                spec["id"],
                job_id,
                "observation_" + digest([spec["id"], job_id]),
                "failed",
                category,
                observed_at.isoformat(),
                json.dumps(spec, ensure_ascii=False, sort_keys=True),
            ),
        )
        self._commit()

    def observations(
        self, document_id: str, *, job_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Return successful and failed observations in persisted chronology."""
        query = "SELECT * FROM observations WHERE document_id=?"
        parameters: tuple[str, ...] = (document_id,)
        if job_id:
            query += " AND job_id=?"
            parameters += (job_id,)
        rows = self.connection.execute(
            query + " ORDER BY sequence", parameters
        ).fetchall()
        return [self._wire(row) for row in rows]

    def read_raw(self, observation: dict[str, Any]) -> bytes:
        """Load private original bytes and verify the content-addressed version."""
        path = self.root / observation["rawStorageKey"]
        if not path.is_relative_to(self.root):
            raise ValueError("invalid raw storage key")
        raw = private_read(path, root=self.root)
        if sha256(raw).hexdigest() != observation["version"]:
            raise ValueError("immutable original conflict")
        return raw

    def version_metadata(self, observation: dict[str, Any]) -> dict[str, str]:
        """Return first raw-version time and the latest actual content transition."""
        first = self.connection.execute(
            "SELECT observed_at FROM observations WHERE document_id=? AND payload_hash=? AND status='success' ORDER BY sequence LIMIT 1",
            (observation["documentId"], observation["version"]),
        ).fetchone()
        transition = self.connection.execute(
            "SELECT observation_id FROM observations WHERE document_id=? AND status='success' AND changed=1 AND sequence<=(SELECT sequence FROM observations WHERE observation_id=?) ORDER BY sequence DESC LIMIT 1",
            (observation["documentId"], observation["observationId"]),
        ).fetchone()
        return {
            "collectedAt": first["observed_at"],
            "transitionId": transition["observation_id"],
        }

    def save_extraction(self, document_id: str, extraction: dict[str, Any]) -> None:
        """Preserve extracted segments independently of every earlier revision."""
        path = (
            self.root
            / "extractions"
            / digest(document_id)
            / (extraction["extractionVersion"] + ".json")
        )
        private_write(
            path,
            json.dumps(
                extraction, ensure_ascii=False, sort_keys=True, indent=2
            ).encode(),
            root=self.root,
        )

    def close(self) -> None:
        """Release the private local observation database."""
        self._resources.close()
