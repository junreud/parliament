"""Historical pilot commands with explicit private output and draft import gates."""

import argparse
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from parliament_worker.http import SafeFetcher
from parliament_worker.knowledge.extract import digest
from parliament_worker.knowledge.guide import review_guide
from parliament_worker.knowledge.pipeline import (
    collect_manifest,
    prepare_batch,
    read_manifest,
)
from parliament_worker.knowledge.review import (
    KnowledgePublisher,
    read_batch,
    review_export,
)
from parliament_worker.knowledge.store import PilotStore, private_write
from parliament_worker.models import SEOUL

LOGGER = logging.getLogger(__name__)


def add_parser(commands: Any) -> None:
    """Register collect/prepare/review-export/validate/import pilot subcommands."""
    pilot = commands.add_parser(
        "pilot", help="explicit historical official-document pilot"
    )
    actions = pilot.add_subparsers(dest="pilot_action", required=True)
    collect = actions.add_parser("collect", help="collect manifest URLs; never publish")
    collect.add_argument("--manifest", type=Path, required=True)
    collect.add_argument("--output", type=Path, required=True)
    collect.add_argument("--job-id", required=True)
    collect.add_argument(
        "--s3",
        action="store_true",
        help="explicit optional immutable cloud preservation",
    )
    prepare = actions.add_parser(
        "prepare", help="prepare unapproved evidence/identity candidates"
    )
    prepare.add_argument("--manifest", type=Path, required=True)
    prepare.add_argument(
        "--output",
        type=Path,
        required=True,
        help="existing private collection directory",
    )
    prepare.add_argument("--job-id", required=True)
    prepare.add_argument(
        "--batch", type=Path, required=True, help="explicit private candidate JSON path"
    )
    for action in ("review-export", "validate", "import"):
        command = actions.add_parser(action)
        command.add_argument("--batch", type=Path, required=True)
        if action in ("review-export", "validate"):
            command.add_argument(
                "--output",
                type=Path,
                required=action == "review-export",
                help="private validated copy; reseals operator changes",
            )
        else:
            command.add_argument(
                "--import",
                dest="import_enabled",
                action="store_true",
                help="required authenticated draft-only import opt-in",
            )
            command.add_argument(
                "--response",
                type=Path,
                help="private server-normalized version receipt",
            )


def _save(path: Path, payload: dict[str, Any], *, immutable: bool = True) -> None:
    """Write private JSON without logging evidence, credentials or local paths."""
    private_write(
        path,
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode(),
        immutable=immutable,
    )


def run(args: argparse.Namespace, options: argparse.ArgumentParser) -> int:
    """Execute one explicit bounded pilot operation without public approval."""
    if args.pilot_action == "import":
        if not args.import_enabled:
            options.error("pilot import requires --import explicit opt-in")
        if not (
            os.environ.get("TRACKING_ADMIN_KEY")
            or os.environ.get("PARLIAMENT_INGESTION_ADMIN_KEY")
        ):
            options.error("pilot import requires configured ingestion admin key")
        batch = read_batch(args.batch)
        publisher = KnowledgePublisher.from_env()
        try:
            response = publisher.import_batch(batch)
            _save(
                args.response
                or args.batch.with_name(args.batch.stem + ".receipt.json"),
                response,
            )
            LOGGER.info("Imported candidate batch; public approval remains pending")
        finally:
            publisher.close()
        return 0
    if args.pilot_action in {"review-export", "validate"}:
        batch = read_batch(args.batch)
        if args.output:
            content = {
                key: value for key, value in review_export(batch).items() if key != "id"
            }
            stable = content | {
                "documents": [
                    {
                        key: value
                        for key, value in document.items()
                        if key not in {"observationId", "observedAt"}
                    }
                    for document in content["documents"]
                ]
            }
            _save(args.output, {"id": "batch_" + digest(stable), **content})
            if args.pilot_action == "review-export":
                _save(
                    args.output.with_name(args.output.stem + ".review-guide.json"),
                    review_guide(batch, args.output.name),
                )
        LOGGER.info("Validated candidate evidence references; no publication requested")
        return 0
    if (
        args.pilot_action == "collect"
        and args.s3
        and not os.environ.get("PARLIAMENT_RAW_BUCKET")
    ):
        options.error("PARLIAMENT_RAW_BUCKET required for --s3")
    manifest = read_manifest(args.manifest)
    store = PilotStore(args.output)
    try:
        if args.pilot_action == "prepare":
            batch = prepare_batch(manifest, store, args.job_id)
            _save(args.batch, batch)
            LOGGER.info(
                "Prepared %s documents with pending name candidates",
                len(batch["documents"]),
            )
            return 0
        fetcher = SafeFetcher(max_bytes=10_000_000, total_timeout=60.0)
        try:
            cloud_store = None
            if args.s3:
                from parliament_worker.aws import S3RawStore

                cloud_store = S3RawStore(
                    os.environ["PARLIAMENT_RAW_BUCKET"], enabled=True
                )
            report = collect_manifest(
                manifest,
                fetcher,
                store,
                args.job_id,
                datetime.now(SEOUL),
                cloud_store=cloud_store,
            )
            _save(args.output / "runs" / f"{args.job_id}.json", report)
            LOGGER.info(
                "Pilot collected %s originals; %s failed; no public approval",
                report["successes"],
                report["failures"],
            )
            return 1 if report["failures"] else 0
        finally:
            fetcher.close()
    finally:
        store.close()
