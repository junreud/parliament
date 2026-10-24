"""Validate the campaign kit and produce honest local reports; never publishes."""

import argparse
import csv
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from marketing.board import validate_board
from marketing.metrics import (
    aggregate_events,
    merge_external_report,
    normalize_backend_report,
    timestamp,
)
from marketing.urls import public_https

LOGGER = logging.getLogger(__name__)
DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "docs/marketing/beta-4w"


def read_csv(path: Path) -> List[Dict[str, str]]:
    """Read an explicitly supplied CSV while preserving blank cells."""
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def budget_summary(rows: List[Dict[str, str]]) -> Dict[str, Any]:
    """Check the approved cap, leaving unrecorded expenditure unknown."""
    planned_values = [int(row["planned_krw"]) for row in rows]
    planned = sum(planned_values)
    actual_values = [
        int(row["actual_krw"]) for row in rows if row["actual_krw"].strip()
    ]
    if any(value < 0 for value in planned_values + actual_values):
        raise ValueError("budget amounts must be non-negative")
    actual = sum(actual_values) if len(actual_values) == len(rows) else None
    known = sum(actual_values)
    if planned > 100000 or known > 100000:
        raise ValueError("approved 100000 KRW cap exceeded")
    return {
        "planned_total_krw": planned,
        "actual_recorded_subtotal_krw": known if actual_values else None,
        "actual_total_krw": actual,
        "within_budget": True,
        "unrecorded_rows": len(rows) - len(actual_values),
    }


def deadline_state(deadline: Optional[str], as_of: datetime) -> str:
    """Identify a bounded collector renewal without restarting any process."""
    if not deadline:
        return "unknown"
    remaining = timestamp(deadline) - timestamp(as_of.isoformat())
    if remaining <= timedelta(0):
        return "expired"
    return "renewal_due" if remaining <= timedelta(days=1) else "within_window"


def measurement_gate(readiness: Dict[str, Any]) -> Dict[str, Any]:
    """Admit real campaign inputs only after an explicit production declaration.

    The production declaration attests to the data source; local technical QA
    or completed editorial checks do not establish real audience observations.
    """
    source = readiness.get("measurement_source")
    source = source if isinstance(source, dict) else {}
    reasons = []
    if source.get("environment") != "production-beta":
        reasons.append("measurement environment is not production-beta")
    if source.get("includeInCampaignMetrics") is not True:
        reasons.append("campaign metric inclusion is not explicitly true")
    if not public_https(readiness.get("public_base_url") or ""):
        reasons.append("verified public HTTPS base URL is missing")
    return {
        "allowed": not reasons,
        "environment": source.get("environment"),
        "include_in_campaign_metrics": source.get("includeInCampaignMetrics") is True,
        "reasons": reasons,
    }


def check(root: Path, as_of: datetime) -> Dict[str, Any]:
    """Read campaign state and distinguish a valid kit from launch readiness."""
    config = json.loads((root / "campaign.json").read_text(encoding="utf-8"))
    readiness = json.loads((root / "readiness.json").read_text(encoding="utf-8"))
    board = read_csv(root / "content-board.csv")
    errors = validate_board(board, config)
    budget = budget_summary(read_csv(root / "budget.csv"))
    blockers = [
        item["label"]
        for item in readiness["checks"]
        if item["status"] != "verified" or not item.get("evidence")
    ]
    if not public_https(readiness.get("public_base_url") or ""):
        blockers.append("공개 HTTPS 모바일 웹 주소 확인")
    public_link_checks = [row["asset_id"] for row in board if row.get("app_url")]
    return {
        "as_of": as_of.isoformat(),
        "campaign_id": config["campaign_id"],
        "kit_valid": not errors,
        "validation_errors": errors,
        "launch_ready": not errors and not blockers,
        "launch_blockers": blockers,
        "measurement_gate": measurement_gate(readiness),
        "planned_assets": len(board),
        "assets_with_public_link_shape": public_link_checks,
        "published_assets": sum(row["status"] == "published" for row in board),
        "budget": budget,
        "collector_deadline_status": deadline_state(config["collector_until"], as_of),
        "collector_until": config["collector_until"],
        "collector_liveness": "not_checked",
        "scheduled_slots_are_not_scheduler_jobs": True,
    }


def report(
    root: Path,
    as_of: datetime,
    events: Optional[Path] = None,
    backend_report: Optional[Path] = None,
    insights: Optional[Path] = None,
) -> Dict[str, Any]:
    """Combine explicitly supplied measurements without fabricated actuals."""
    result = check(root, as_of)
    admitted = result["measurement_gate"]["allowed"]
    result["ignored_measurement_inputs"] = [
        name
        for name, path in (("events", events), ("backend-report", backend_report))
        if path and not admitted
    ]
    result["research_export"] = aggregate_events(
        read_csv(events) if events and admitted else None, as_of
    )
    backend = (
        json.loads(backend_report.read_text(encoding="utf-8"))
        if backend_report and admitted
        else None
    )
    result["backend_aggregate"] = merge_external_report(backend)
    result["backend_metrics"] = normalize_backend_report(backend)
    result["instagram_insights"] = read_csv(insights) if insights else None
    result["measurement_notes"] = [
        "null means unmeasured or unavailable, not zero",
        "D7 denominator requires full 168 hours after activation",
        "friend/external and organic/prompted are separate",
        "backend aggregate is attributed and not added to private-export totals",
        "planned slots and reserved incentives are not completed publications or payments",
    ]
    if result["ignored_measurement_inputs"]:
        result["measurement_notes"].append(
            "Ignored QA/unverified measurement inputs; actual campaign values remain null. "
            "Require production-beta, explicit inclusion=true and verified public HTTPS base."
        )
    elif not admitted:
        result["measurement_notes"].append(
            "Actual campaign measurement source is not enabled; local QA is not audience data."
        )
    return result


def main() -> int:
    """Run local checks or a JSON report without network, publishing or secrets."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "report"))
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--as-of", required=True, help="Offset-aware ISO timestamp")
    parser.add_argument(
        "--events", type=Path, help="Private consented topic-free event CSV"
    )
    parser.add_argument(
        "--backend-report", type=Path, help="Authenticated /admin/beta/report export"
    )
    parser.add_argument(
        "--insights", type=Path, help="Explicit Instagram aggregate CSV"
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        as_of = timestamp(args.as_of)
        result = (
            check(args.root, as_of)
            if args.command == "check"
            else report(
                args.root, as_of, args.events, args.backend_report, args.insights
            )
        )
        rendered = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered + "\n", encoding="utf-8")
        LOGGER.info("%s", rendered)
        return 0 if result["kit_valid"] else 1
    except (KeyError, OSError, TypeError, ValueError) as error:
        LOGGER.error("Campaign check failed: %s", error)
        return 2


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    raise SystemExit(main())
