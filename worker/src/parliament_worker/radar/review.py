"""Fixed official evidence for private editorial recommendations."""

import hashlib
import json
from datetime import datetime
from pathlib import Path

from parliament_worker.http import validate_official_url


def preserve_evidence(
    directory: Path, url: str, raw: bytes, collected_at: str, locator: str, scope: str
) -> dict[str, str]:
    """Bind an editorial claim scope to exact original bytes and a source location.

    Args:
        directory: Private evidence directory, never the public feed path.
        url: Operator-reviewed official HTTPS document URL.
        raw: Original document response bytes.
        collected_at: Explicit aware collection timestamp.
        locator: Section, paragraph, or JSON location actually inspected.
        scope: Limited fact supported by that location.

    Returns:
        Version-pinned evidence metadata without declaring human approval.
    """
    validate_official_url(url)
    stamp = datetime.fromisoformat(collected_at.replace("Z", "+00:00"))
    if (
        not stamp.tzinfo
        or not locator.strip()
        or not scope.strip()
        or len(raw) > 10_000_000
    ):
        raise ValueError("bounded evidence and explicit scope required")
    directory.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(raw).hexdigest()
    target = directory / (digest + ".bin")
    if target.exists():
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError("evidence archive integrity mismatch")
    else:
        target.write_bytes(raw)
    record = {
        "url": url,
        "sha256": digest,
        "collectedAt": collected_at,
        "locator": locator,
        "scope": scope,
        "rawPath": str(target),
        "reviewStatus": "source-checked-awaiting-human-review",
    }
    identity = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
    metadata = directory / (identity + ".evidence.json")
    if not metadata.exists():
        metadata.write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return record
