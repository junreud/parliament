"""Consistent read bundle for private GraphRAG question planning."""

from typing import TYPE_CHECKING, Any

from parliament_worker.graphrag.status import status_from_db
from parliament_worker.graphrag.store_sources import source_row

if TYPE_CHECKING:
    from parliament_worker.graphrag.store import GraphStore


def query_snapshot(store: "GraphStore") -> dict[str, Any]:
    """Read source, graph, report, model, and coverage from one revision.

    Args:
        store: Private graph store using atomic whole-file replacement.

    Returns:
        A consistent bundle for one question request.
    """
    with store._transaction(write=False) as db:
        sources = [
            source_row(row)
            for row in db.execute("SELECT * FROM sources WHERE active=1 ORDER BY scope")
        ]
        artifacts: dict[str, list[dict[str, Any]]] = {"graph": [], "community": []}
        for row in db.execute(
            "SELECT * FROM artifacts WHERE current=1 AND kind IN ('graph','community') ORDER BY sequence"
        ):
            artifacts[row["kind"]].append(store._artifact(row))
        model = db.execute(
            "SELECT * FROM artifacts WHERE current=1 AND kind='control' "
            "AND artifact_key='model' ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        return {
            "sources": sources,
            "artifacts": artifacts,
            "model": store._artifact(model) if model else None,
            "coverage": status_from_db(db),
        }
