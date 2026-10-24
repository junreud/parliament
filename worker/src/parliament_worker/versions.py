"""Archive exact Java source versions and conservatively map known bill records."""

import hashlib
import json
import re
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from parliament_worker.activity import version_activity
from parliament_worker.aws import validate_version_message
from parliament_worker.http import validate_official_url
from parliament_worker.parsing import parse_date

BILL_STAGES = {
    "원안가결": "passed",
    "수정가결": "passed",
    "대안반영폐기": "alternative",
    "폐기": "rejected",
    "부결": "rejected",
    "철회": "withdrawn",
}
MAPPER_VERSION = "assembly-record-v3"


class VersionArchive:
    """Resolve an immutable raw DB version; unsupported mappings stay explicit."""

    def __init__(
        self, root: Path, load: Callable[[dict[str, Any]], dict[str, Any]]
    ) -> None:
        self.root = root
        self.load = load

    def process(self, message: dict[str, Any]) -> Path:
        """Archive one exact identity/version idempotently before acknowledgement."""
        validate_version_message(message)
        row = self.load(message)
        if any(
            row.get(key) != message[wire]
            for key, wire in (
                ("source_key", "sourceKey"),
                ("record_key", "recordKey"),
                ("payload_hash", "payloadHash"),
            )
        ):
            raise ValueError("original version identity mismatch")
        identity = hashlib.sha256(
            f"{row['source_key']}:{row['record_key']}".encode()
        ).hexdigest()
        version = row["payload_hash"]
        raw_directory = self.root / "raw" / "java" / identity
        raw_directory.mkdir(parents=True, exist_ok=True)
        raw = row["raw_payload"]
        if isinstance(raw, (str, bytes)):
            raw = json.loads(raw)
        if not isinstance(raw, dict):
            raise ValueError("original record object required")
        raw_path = raw_directory / f"{version}.json"
        raw_bytes = json.dumps(
            raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        try:
            with raw_path.open("xb") as handle:
                handle.write(raw_bytes)
        except FileExistsError:
            if raw_path.read_bytes() != raw_bytes:
                raise ValueError("immutable original version conflict")
        processed_directory = self.root / "processed" / identity
        processed_directory.mkdir(parents=True, exist_ok=True)
        event = map_bill(row, raw, identity)
        result = {
            "sourceKey": row["source_key"],
            "recordKey": row["record_key"],
            "apiCode": row["api_code"],
            "sourceVersion": version,
            "parserVersion": MAPPER_VERSION,
            "snapshotSha256": hashlib.sha256(raw_bytes).hexdigest(),
            "status": "structural_draft" if event else "unsupported_record_type",
            "event": event,
            "coverage": "Only known bill fields are mapped; votes, transcripts and other API records require dedicated mappings. No AI claim was generated.",
        }
        derived_digest = hashlib.sha256(
            json.dumps(
                result, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        result_path = processed_directory / f"{derived_digest}.json"
        if result_path.exists():
            if json.loads(result_path.read_text()) != result:
                raise ValueError("immutable derived version conflict")
            return result_path
        try:
            with result_path.open("x", encoding="utf-8") as handle:
                json.dump(result, handle, ensure_ascii=False, indent=2)
        except FileExistsError:
            pass
        return result_path


def map_bill(
    row: dict[str, Any], raw: dict[str, Any], identity: str
) -> dict[str, Any] | None:
    """Map a bill only when its identity, publication and original URL are explicit.

    No people, votes, action time or explanatory claims are inferred from a title.
    Unsupported records remain preserved for future dedicated normalizers.
    """
    bill_id = str(raw.get("BILL_ID", ""))
    title = raw.get("BILL_NAME")
    published = parse_date(raw.get("PROPOSE_DT"))
    url = raw.get("DETAIL_LINK") or raw.get("BILL_LINK") or raw.get("LINK_URL")
    if (
        not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", bill_id)
        or not isinstance(title, str)
        or not title.strip()
        or published is None
        or not isinstance(url, str)
    ):
        return None
    try:
        validate_official_url(url)
    except ValueError:
        return None
    observed = row["observed_at"]
    if isinstance(observed, str):
        observed = datetime.fromisoformat(observed)
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    result = raw.get("PROC_RESULT") or raw.get("PROC_RESULT_CD")
    stage = BILL_STAGES.get(result, "unknown")
    version = row["payload_hash"]
    excerpt = json.dumps(
        {
            key: raw[key]
            for key in (
                "BILL_ID",
                "BILL_NAME",
                "PROPOSE_DT",
                "PROC_RESULT",
                "PROC_RESULT_CD",
            )
            if key in raw
        },
        ensure_ascii=False,
    )
    payload = {
        "id": f"assembly_{identity}",
        "type": "bill",
        "title": title[:500],
        "summary": None,
        "stage": stage,
        "personIds": [],
        "topics": [],
        "billId": bill_id,
        "occurredAt": None,
        "publishedAt": published.isoformat(),
        "collectedAt": observed.isoformat(),
        "sourceUrl": url,
        "evidence": [
            {
                "id": f"ev_{identity}",
                "sourceUrl": url,
                "excerpt": excerpt,
                "locator": f"JSON record key {row['record_key']}: BILL_ID/BILL_NAME/PROPOSE_DT/PROC_RESULT",
                "sourceVersion": version,
            }
        ],
        "votes": [],
        "coverage": "공식 의안 공개 기록의 발의일(PROPOSE_DT)과 처리 결과. 개인별 표결·발언·시행 여부는 이 기록에서 확인되지 않습니다.",
        "corrected": False,
    }
    return version_activity(payload, MAPPER_VERSION)
