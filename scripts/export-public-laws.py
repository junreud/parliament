"""Export reviewed public legal metadata for the app's explicit offline collection view."""

import argparse
import json
import logging
import re
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

LOGGER = logging.getLogger(__name__)
MAX_BYTES = 1_048_576
LAW_FIELDS = {
    "id",
    "lawId",
    "mst",
    "title",
    "agency",
    "promulgationNumber",
    "promulgatedDate",
    "effectiveDate",
    "collectedAt",
    "sourceUrl",
    "sourceVersion",
    "extractionVersion",
    "evidence",
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a public export request to another destination."""

    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


def validate(payload: Any) -> dict[str, Any]:
    """Validate and retain only the credential-free public API response.

    Args:
        payload: Decoded response from GET /api/v1/laws after publication review.

    Returns:
        The original validated public response, without enrichment or date substitution.
    """
    if (
        not isinstance(payload, dict)
        or set(payload) != {"items", "coverage", "nextCursor"}
        or payload["nextCursor"] is not None
        or not isinstance(payload["coverage"], str)
        or not isinstance(payload["items"], list)
        or len(payload["items"]) > 50
    ):
        raise ValueError("invalid_public_law_page")
    ids: set[str] = set()
    for law in payload["items"]:
        if not isinstance(law, dict) or set(law) != LAW_FIELDS:
            raise ValueError("unexpected_public_law_fields")
        if (
            not re.fullmatch(r"[0-9]{1,12}", law["lawId"])
            or not re.fullmatch(r"[0-9]{1,12}", law["mst"])
            or law["id"] != f"law_{law['lawId']}_{law['mst']}"
            or law["id"] in ids
            or law["sourceUrl"]
            != f"https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq={law['mst']}"
            or not re.fullmatch(r"[a-f0-9]{64}", law["sourceVersion"])
        ):
            raise ValueError("invalid_public_law_identity")
        ids.add(law["id"])
        for name in ("promulgatedDate", "effectiveDate"):
            if (
                law[name] is not None
                and date.fromisoformat(law[name]).isoformat() != law[name]
            ):
                raise ValueError("invalid_public_law_date")
        if (
            datetime.fromisoformat(law["collectedAt"].replace("Z", "+00:00")).tzinfo
            is None
        ):
            raise ValueError("invalid_public_collection_time")
        if not isinstance(law["evidence"], list) or not 1 <= len(law["evidence"]) <= 6:
            raise ValueError("invalid_public_law_evidence")
        for evidence in law["evidence"]:
            if (
                not isinstance(evidence, dict)
                or set(evidence) != {"label", "text", "locator"}
                or not re.fullmatch(
                    r"json:법령\.기본정보\.(법령명_한글|법령ID|공포일자|시행일자|공포번호|소관부처\.content)",
                    evidence["locator"],
                )
            ):
                raise ValueError("invalid_public_law_locator")
    return payload


def main() -> None:
    """Read an already-public API and atomically update the bundled collection."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default="http://127.0.0.1:8080")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    origin = urlparse(args.origin)
    if (
        origin.username
        or origin.password
        or origin.path not in ("", "/")
        or origin.query
        or origin.fragment
        or not origin.hostname
        or (
            origin.scheme != "https"
            and not (origin.scheme == "http" and origin.hostname == "127.0.0.1")
        )
    ):
        raise ValueError("https_or_loopback_origin_required")
    request = urllib.request.Request(
        args.origin.rstrip("/") + "/api/v1/laws", headers={"Accept": "application/json"}
    )
    with urllib.request.build_opener(NoRedirect).open(request, timeout=10) as response:
        raw = response.read(MAX_BYTES + 1)
        if response.status != 200 or len(raw) > MAX_BYTES:
            raise ValueError("public_law_export_failed")
    payload = validate(json.loads(raw.decode("utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(args.output)
    LOGGER.info("Exported %d public law records", len(payload["items"]))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
