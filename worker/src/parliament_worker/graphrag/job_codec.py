"""Losslessly pack durable jobs while leaving SQL routing fields visible."""

import base64
import json
import zlib
from typing import Any

from parliament_worker.graphrag.store_schema import canonical_json

PACKED_FORMAT = "zlib-json-v1"
MAX_JOB_BYTES = 4_000_000
MIN_JOB_BYTES = 1_024
ROUTING_CONTEXT_KEYS = ("artifact_key", "question_id")


def encode_job(job: dict[str, Any]) -> str:
    """Store full job history without discarding its request or remote identity."""
    original = canonical_json(job)
    raw = original.encode("utf-8")
    if len(raw) < MIN_JOB_BYTES:
        return original
    if len(raw) > MAX_JOB_BYTES:
        raise ValueError("graph job exceeds packed storage limit")
    context = job["context"]
    if not isinstance(context, dict):
        raise ValueError("graph job context must be an object")
    routing = {key: context[key] for key in ROUTING_CONTEXT_KEYS if key in context}
    packed = {
        "_format": PACKED_FORMAT,
        "_packed": base64.b64encode(zlib.compress(raw, level=6)).decode("ascii"),
        "id": job["id"],
        "kind": job["kind"],
        "key": job["key"],
        "state": job["state"],
        "context": routing,
    }
    encoded = canonical_json(packed)
    return encoded if len(encoded.encode("utf-8")) < len(raw) else original


def decode_job(data: str) -> dict[str, Any]:
    """Read both historical plain JSON and bounded packed job revisions."""
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("graph job must be an object")
    if "_format" not in value:
        return value
    if value.get("_format") != PACKED_FORMAT or not isinstance(
        value.get("_packed"), str
    ):
        raise ValueError("unsupported packed graph job")
    try:
        compressed = base64.b64decode(value["_packed"], validate=True)
        decoder = zlib.decompressobj()
        raw = decoder.decompress(compressed, MAX_JOB_BYTES + 1)
        if (
            len(raw) > MAX_JOB_BYTES
            or not decoder.eof
            or decoder.unused_data
            or decoder.unconsumed_tail
        ):
            raise ValueError("invalid packed graph job length")
        restored = json.loads(raw)
    except (ValueError, zlib.error, UnicodeDecodeError) as error:
        raise ValueError("invalid packed graph job") from error
    if not isinstance(restored, dict):
        raise ValueError("packed graph job must be an object")
    if any(
        restored.get(key) != value.get(key) for key in ("id", "kind", "key", "state")
    ):
        raise ValueError("packed graph job routing fields disagree")
    context = restored.get("context")
    if not isinstance(context, dict) or value.get("context") != {
        key: context[key] for key in ROUTING_CONTEXT_KEYS if key in context
    }:
        raise ValueError("packed graph job context disagrees")
    return restored
