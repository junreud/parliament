"""Explicit bounded official bill intake for private graph generation."""

import argparse
import hashlib
import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from parliament_worker.bill_collect import collect_bill_cycle
from parliament_worker.graphrag.store import GraphStore
from parliament_worker.http import SafeFetcher
from parliament_worker.knowledge.files import private_write
from parliament_worker.models import SEOUL

LOGGER = logging.getLogger(__name__)
MAX_BILL_GRAPH_BYTES = 1_300_000_000
MIN_BILL_FREE_BYTES = 10 * 1024**3


def _capacity_issue(
    graph_state: Path, graph_input: Path, state_dir: Path
) -> str | None:
    """Fail closed before fetching if private bill intake lacks storage headroom."""
    if (graph_state / "graph.sqlite3").stat().st_size >= MAX_BILL_GRAPH_BYTES:
        return "graph database reached the 1.3 GB bill intake limit"
    destinations = (
        graph_state,
        graph_input,
        state_dir if state_dir.exists() else state_dir.parent,
    )
    if any(
        shutil.disk_usage(destination).free < MIN_BILL_FREE_BYTES
        for destination in destinations
    ):
        return "bill intake destination has less than 10 GiB free"
    return None


def add_parser(commands: Any) -> None:
    """Register a bounded read-and-stage operation, never a public import."""
    bills = commands.add_parser("bills", help="collect official bill graph candidates")
    actions = bills.add_subparsers(dest="bill_action", required=True)
    collect = actions.add_parser("collect-graph")
    collect.add_argument("--graph-state", type=Path, required=True)
    collect.add_argument("--graph-input", type=Path, required=True)
    collect.add_argument("--state", type=Path, required=True)
    collect.add_argument("--hot-pages", type=int, default=1)
    collect.add_argument("--sweep-pages", type=int, default=1)
    collect.add_argument("--sweep-start", type=int)
    collect.add_argument("--request-gap-seconds", type=float, default=0.2)


def run(args: argparse.Namespace, options: argparse.ArgumentParser) -> int:
    """Collect selected HTML revisions and stage only changed private bills."""
    if args.bill_action != "collect-graph":
        options.error("unsupported bills action")
    if not (args.graph_state / "graph.sqlite3").is_file():
        options.error("existing GraphRAG state is required")
    if args.state.is_symlink():
        options.error("unsafe bill state directory")
    capacity_issue = _capacity_issue(args.graph_state, args.graph_input, args.state)
    if capacity_issue:
        LOGGER.warning("Bill graph collection paused: %s", capacity_issue)
        return 1
    args.state.mkdir(parents=True, exist_ok=True, mode=0o700)
    fetcher = SafeFetcher()
    try:
        report = collect_bill_cycle(
            fetcher,
            args.graph_input,
            args.state,
            GraphStore(args.graph_state).sources(),
            observed_at=datetime.now(SEOUL).isoformat(),
            hot_pages=args.hot_pages,
            sweep_pages=args.sweep_pages,
            sweep_start=args.sweep_start,
            request_gap_seconds=args.request_gap_seconds,
        )
    finally:
        fetcher.close()
    encoded = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2).encode()
    report_id = hashlib.sha256(encoded).hexdigest()
    private_write(args.state / "reports" / (report_id + ".json"), encoded)
    LOGGER.info(
        "Bill graph cycle visited_pages=%s staged=%s unchanged=%s curated_holds=%s failures=%s",
        len(report["visitedPages"]),
        report["stagedBillCount"],
        report["unchangedBillCount"],
        len(report["curatedHold"]),
        len(report["failures"]),
    )
    return 1 if report["failures"] else 0
