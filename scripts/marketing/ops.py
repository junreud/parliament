"""Run an evidence-only daily desk; never upload, contact or publish."""

import argparse
import hashlib
import json
import logging
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from marketing.campaign import DEFAULT_ROOT, check, read_csv
from marketing.growth import observation, publication_preflight, save_observation
from marketing.metrics import timestamp

LOGGER = logging.getLogger(__name__)


def desk(root: Path, as_of: datetime) -> Dict[str, Any]:
    """List real pending work and distinguish elapsed plans from reservations."""
    rows = read_csv(root / "content-board.csv")
    now = timestamp(as_of.isoformat())
    config = json.loads((root / "campaign.json").read_text())
    upcoming = [r for r in rows if timestamp(r["scheduled_at"]) > now]
    overdue = [
        r["asset_id"]
        for r in rows
        if timestamp(r["scheduled_at"]) <= now and not r.get("published_url")
    ]
    first = upcoming[0] if upcoming else None
    return {
        "as_of": now.isoformat(),
        "check": check(root, now),
        "elapsed_without_publication_evidence": overdue,
        "remaining_planning_slots": len(upcoming),
        "remaining_format_mix": dict(Counter(r["format"] for r in upcoming)),
        "next_asset": first["asset_id"] if first else None,
        "next_planned_at": first["scheduled_at"] if first else None,
        "next_preflight_holds": publication_preflight(first, now) if first else [],
        "confirmed_platform_schedules": [
            r["asset_id"]
            for r in rows
            if r.get("scheduler_id") and r.get("scheduler_receipt")
        ],
        "monthly_planned_feed_slots": dict(
            Counter(r["scheduled_at"][:7] for r in rows)
        ),
        "monthly_planner_publication_cap": config.get(
            "planner_monthly_publication_cap"
        ),
        "monthly_other_publications": "unknown; verify planner before each reservation",
        "audience_actuals": None,
    }


def main() -> int:
    """Create a local desk report, release preflight or immutable observation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("desk", "preflight", "observe"))
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--asset")
    parser.add_argument("--raw", type=Path)
    parser.add_argument("--raw-evidence", type=Path)
    parser.add_argument("--window", type=int, choices=(24, 72))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        now = timestamp(args.as_of)
        if args.command == "desk":
            result = desk(args.root, now)
        else:
            row = next(
                r
                for r in read_csv(args.root / "content-board.csv")
                if r["asset_id"] == args.asset
            )
            if args.command == "preflight":
                errors = check(args.root, now)["validation_errors"]
                errors += publication_preflight(row, now)
                result = {
                    "asset_id": args.asset,
                    "allowed": not errors,
                    "holds": errors,
                }
            else:
                if not all([args.raw, args.raw_evidence, args.window, args.output]):
                    raise ValueError(
                        "observe requires --raw, --raw-evidence, --window and --output"
                    )
                if not args.raw_evidence.is_file():
                    raise ValueError("provider raw response evidence missing")
                raw = json.loads(args.raw.read_text())
                result = observation(row, raw, now, args.window)
                if result is None:
                    raise ValueError(
                        "observation absent, immature, already read or mismatched"
                    )
                result["raw_evidence"] = str(args.raw_evidence)
                result["raw_sha256"] = hashlib.sha256(
                    args.raw_evidence.read_bytes()
                ).hexdigest()
                result["provider"] = (
                    "Metricool; normalized fields require original response review"
                )
                expected = DEFAULT_ROOT.parents[2] / ".local/marketing/observations"
                canonical = expected / f"{args.asset}-{args.window}h.json"
                if args.output.resolve() != canonical.resolve():
                    raise ValueError(
                        f"observation output must be canonical: {canonical}"
                    )
                save_observation(result, expected)
        rendered = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output and args.command != "observe":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            # Observation output cannot be overwritten to inflate repeated measurements.
            mode = "x" if args.command == "observe" else "w"
            with args.output.open(mode, encoding="utf-8") as stream:
                stream.write(rendered + "\n")
        LOGGER.info("%s", rendered)
        return 1 if result.get("allowed") is False else 0
    except (ValueError, OSError, StopIteration) as error:
        LOGGER.error("Daily desk held: %s", error)
        return 2


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(main())
