"""Derived activity versions are separate from immutable evidence source hashes."""

import json
from hashlib import sha256
from typing import Any


def version_activity(payload: dict[str, Any], parser_version: str) -> dict[str, Any]:
    """Bind a deterministic draft version to parser and exact structural payload.

    The source identity/evidence hashes remain unchanged. Callers preserve the
    first collectedAt before invoking this function; wall-clock processing time
    must never replace it. Existing version is excluded from the canonical input.
    """
    structural = {key: value for key, value in payload.items() if key != "version"}
    canonical = json.dumps(
        {"parserVersion": parser_version, "activity": structural},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return structural | {"version": "v_" + sha256(canonical).hexdigest()}
