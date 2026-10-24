"""Decode source rows without adding more storage policy to the main store."""

import json
import sqlite3
from typing import Any


def source_row(row: sqlite3.Row) -> dict[str, Any]:
    """Return a source row with its active flag and optional payload decoded.

    Args:
        row: SQLite source row, possibly omitting the payload column.

    Returns:
        Source dictionary used by incremental planners.
    """
    return {
        **dict(row),
        **({"payload": json.loads(row["payload"])} if "payload" in row.keys() else {}),
        "active": bool(row["active"]),
    }
