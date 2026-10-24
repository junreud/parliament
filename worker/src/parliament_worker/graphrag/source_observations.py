"""Record when a fixed source revision was collected, without revising its graph."""

import sqlite3
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from parliament_worker.graphrag.store import GraphStore


def normalize_observed_at(value: Any) -> str | None:
    """Require a timezone-aware source collection time and normalize it to UTC."""
    if value is None or value == "":
        return None
    if not isinstance(value, str) or "T" not in value:
        raise ValueError("invalid source observation time")
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("invalid source observation time") from error
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError("source observation time requires timezone")
    return observed.astimezone(timezone.utc).isoformat()


class SourceObservationMixin:
    """Keep collection times separate from immutable semantic source versions."""

    def source_observation_times(self: "GraphStore") -> dict[str, str]:
        """Return the latest collection time for each currently active revision."""
        with self._transaction(write=False) as db:
            return {
                row["scope"]: row["last_observed_at"]
                for row in db.execute(
                    "SELECT s.scope, t.last_observed_at FROM sources s "
                    "JOIN source_observation_times t ON t.scope=s.scope "
                    "AND t.fingerprint=s.fingerprint AND t.generation=s.generation "
                    "WHERE s.active=1"
                )
            }

    def source_observations_for_documents(
        self: "GraphStore", document_ids: set[str]
    ) -> list[dict[str, str]]:
        """Expose current collection times for selected private answer sources."""
        if not document_ids:
            return []
        if len(document_ids) > 32 or any(
            not isinstance(document_id, str) or not document_id
            for document_id in document_ids
        ):
            raise ValueError("invalid source observation lookup")
        placeholders = ",".join("?" for _ in document_ids)
        with self._transaction(write=False) as db:
            rows = db.execute(
                "SELECT json_extract(s.payload,'$.document.sourceUrl') AS source_url, "
                "t.last_observed_at AS observed_at FROM sources s "
                "JOIN source_observation_times t ON t.scope=s.scope "
                "AND t.fingerprint=s.fingerprint AND t.generation=s.generation "
                "WHERE s.active=1 AND json_extract(s.payload,'$.document.id') "
                f"IN ({placeholders}) ORDER BY source_url, observed_at",
                tuple(sorted(document_ids)),
            ).fetchall()
        return [
            {
                "sourceUrl": row["source_url"],
                "observedAt": row["observed_at"],
                "meaning": "collection_time_only",
            }
            for row in rows
            if isinstance(row["source_url"], str) and row["source_url"]
        ]

    def record_source_observations(
        self: "GraphStore", items: list[dict[str, Any]]
    ) -> int:
        """Advance observed times for current revisions without changing generations."""
        with self._transaction() as db:
            return sum(self._record_source_observation(db, item) for item in items)

    @staticmethod
    def _record_source_observation(
        db: sqlite3.Connection, item: dict[str, Any]
    ) -> bool:
        """Ignore older observations and reject an observation of stale content."""
        observed_at = normalize_observed_at(item.get("observedAt"))
        if observed_at is None:
            return False
        source = db.execute(
            "SELECT fingerprint,generation,active FROM sources WHERE scope=?",
            (item["scope"],),
        ).fetchone()
        if (
            not source
            or not source["active"]
            or source["fingerprint"] != item["fingerprint"]
        ):
            raise ValueError("source observation requires current source revision")
        prior = db.execute(
            "SELECT last_observed_at FROM source_observation_times "
            "WHERE scope=? AND fingerprint=? AND generation=?",
            (item["scope"], item["fingerprint"], source["generation"]),
        ).fetchone()
        if prior is not None:
            if observed_at <= prior["last_observed_at"]:
                return False
            db.execute(
                "UPDATE source_observation_times SET last_observed_at=? "
                "WHERE scope=? AND fingerprint=? AND generation=?",
                (observed_at, item["scope"], item["fingerprint"], source["generation"]),
            )
            return True
        db.execute(
            "INSERT INTO source_observation_times VALUES(?,?,?,?,?)",
            (
                item["scope"],
                item["fingerprint"],
                source["generation"],
                observed_at,
                observed_at,
            ),
        )
        return True
