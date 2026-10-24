"""Bounded news radar collection commands; no model calls or social publication."""

import argparse
import fcntl
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from parliament_worker.radar.feeds import NewsFetcher
from parliament_worker.radar.pipeline import collect_once, write_json

LOGGER = logging.getLogger(__name__)


def add_parser(commands: argparse._SubParsersAction) -> None:
    """Register collection and bounded watching with explicit output paths."""
    command = commands.add_parser(
        "radar", help="collect public news metadata and issue candidates"
    )
    command.add_argument("action", choices=["collect", "watch", "evidence"])
    command.add_argument("--state", type=Path, required=True)
    command.add_argument("--public-output", type=Path)
    command.add_argument("--url")
    command.add_argument("--locator")
    command.add_argument("--scope")
    command.add_argument("--snapshot-output", type=Path)
    command.add_argument("--interval-seconds", type=int, default=1800)
    command.add_argument("--until", help="required ISO timestamp for bounded watch")


def run(args: argparse.Namespace, options: argparse.ArgumentParser) -> int:
    """Run once or watch until a fixed deadline; failures remain visible in the feed."""
    if args.action == "evidence":
        from parliament_worker.http import SafeFetcher
        from parliament_worker.radar.review import preserve_evidence

        if not args.url or not args.locator or not args.scope:
            options.error("evidence requires --url --locator --scope")
        fetcher = SafeFetcher()
        try:
            record = preserve_evidence(
                args.state,
                args.url,
                fetcher(args.url),
                datetime.now(timezone.utc).isoformat(),
                args.locator,
                args.scope,
            )
            LOGGER.info("Official evidence preserved sha256=%s", record["sha256"])
            return 0
        finally:
            fetcher.close()
    if args.public_output is None:
        options.error("collect/watch require --public-output")
    if not 900 <= args.interval_seconds <= 86400:
        options.error("--interval-seconds must be 900..86400")
    until = None
    if args.action == "watch":
        try:
            until = datetime.fromisoformat(args.until.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            if (
                until.tzinfo is None
                or not 0 < (until - now).total_seconds() <= 8 * 86400
            ):
                raise ValueError("invalid deadline")
        except (AttributeError, ValueError, TypeError):
            options.error("watch requires an aware --until within the next 8 days")
    args.state.mkdir(parents=True, exist_ok=True)
    watch_lock = (args.state / "watch.lock").open("a")
    if until is not None:
        try:
            fcntl.flock(watch_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            watch_lock.close()
            options.error("a radar watcher is already running")
    fetcher = NewsFetcher()
    try:
        while until is None or datetime.now(timezone.utc) < until:
            now = datetime.now(timezone.utc)
            page = collect_once(args.state, args.public_output, now, fetcher)
            if args.snapshot_output:
                write_json(args.snapshot_output, page)
            write_json(
                args.state / "watch-status.json",
                {
                    "pid": os.getpid(),
                    "lastRunAt": now.isoformat(),
                    "until": until.isoformat() if until else None,
                    "status": page["status"],
                    "candidates": len(page["items"]),
                },
            )
            LOGGER.info(
                "Radar status=%s candidates=%s run=%s",
                page["status"],
                len(page["items"]),
                page["runId"],
            )
            if until is None:
                return 1 if page["status"] == "unavailable" else 0
            time.sleep(
                min(
                    args.interval_seconds,
                    max(0, (until - datetime.now(timezone.utc)).total_seconds()),
                )
            )
        return 0
    finally:
        fetcher.close()
        watch_lock.close()
