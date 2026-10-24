"""Explicit law collection and private staging; never approve public content."""

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from parliament_worker.knowledge.extract import digest
from parliament_worker.knowledge.files import private_read, private_write
from parliament_worker.knowledge.pipeline import ID_PATTERN
from parliament_worker.knowledge.review import KnowledgePublisher
from parliament_worker.knowledge.store import PilotStore
from parliament_worker.law import collect_laws, prepare_law_batch
from parliament_worker.law_client import LawClient
from parliament_worker.models import SEOUL

LOGGER = logging.getLogger(__name__)


def add_parser(commands: Any) -> None:
    """Register a name-selected bounded collector with explicit staging opt-in."""
    command = commands.add_parser("law", help="version-pinned official law originals")
    actions = command.add_subparsers(dest="law_action", required=True)
    collect = actions.add_parser("collect")
    collect.add_argument("--query", required=True)
    collect.add_argument("--issue-id", required=True)
    collect.add_argument("--max-records", type=int, default=3)
    collect.add_argument("--max-pages", type=int, default=1)
    collect.add_argument("--output", type=Path)
    collect.add_argument("--job-id")
    collect.add_argument("--import", dest="import_enabled", action="store_true")


def _save(path: Path, content: dict[str, Any], root: Path) -> None:
    """Save immutable private JSON under the explicit original storage root."""
    private_write(
        path,
        json.dumps(content, ensure_ascii=False, sort_keys=True, indent=2).encode(),
        root=root,
    )


def _stable(batch: dict[str, Any]) -> dict[str, Any]:
    """Compare fixed batch content independently of repeated observation IDs."""
    return batch | {
        "documents": [
            {
                key: value
                for key, value in doc.items()
                if key not in {"observationId", "observedAt"}
            }
            for doc in batch["documents"]
        ]
    }


def _save_batch(store: PilotStore, batch: dict[str, Any], job_id: str) -> None:
    """Keep the first snapshot and every job's distinct observation envelope."""
    first = store.root / "knowledge-batches" / (batch["id"] + ".json")
    if first.exists():
        previous = json.loads(private_read(first, root=store.root))
        if _stable(previous) != _stable(batch):
            raise ValueError("immutable_law_batch_conflict")
    else:
        _save(first, batch, store.root)
    _save(
        store.root / "knowledge-batches" / job_id / (batch["id"] + ".json"),
        batch,
        store.root,
    )


def run(args: argparse.Namespace, options: argparse.ArgumentParser) -> int:
    """Collect and optionally import a bounded evidence batch as pending only."""
    if args.import_enabled and not args.output:
        options.error("law --import requires --output for original preservation")
    if args.output and not args.job_id:
        options.error("law --output requires --job-id for repeatable observations")
    if (
        not ID_PATTERN.fullmatch(args.issue_id)
        or not 1 <= args.max_records <= 20
        or not 1 <= args.max_pages <= 5
    ):
        options.error("law requires a valid issue ID and bounded records/pages")
    job_id = args.job_id or "preview_" + uuid4().hex
    if (
        not ID_PATTERN.fullmatch(job_id)
        or not args.query.strip()
        or len(args.query) > 200
    ):
        options.error("invalid law job ID or query")
    publisher = KnowledgePublisher.from_env() if args.import_enabled else None
    client, store = None, None
    try:
        client = LawClient.from_env()
        store = PilotStore(args.output) if args.output else None
        report = collect_laws(
            client,
            args.query,
            store=store,
            job_id=job_id,
            collected_at=datetime.now(SEOUL),
            max_records=args.max_records,
            max_pages=args.max_pages,
        )
        if store:
            batch = prepare_law_batch(report, store, issue_id=args.issue_id)
            _save_batch(store, batch, job_id)
            if publisher and not report["failures"] and batch["documents"]:
                response = publisher.import_batch(batch)
                _save(
                    store.root
                    / "receipts"
                    / batch["id"]
                    / (digest(response) + ".json"),
                    response,
                    store.root,
                )
                LOGGER.info(
                    "Law evidence staged privately; public approval remains pending"
                )
        LOGGER.info(
            "Law originals=%s failures=%s full_query=%s",
            report["successes"],
            report["failures"],
            report["complete"],
        )
        return 1 if report["failures"] else 0 if report["complete"] else 2
    finally:
        if store:
            store.close()
        if client:
            client.close()
        if publisher:
            publisher.close()
