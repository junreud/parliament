"""Read-only collection default; filesystem/backend/AWS writes are explicit."""

import argparse
import json
import logging
import os
import traceback
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from parliament_worker.connectors import SOURCES, collect
from parliament_worker.content import document_body_status
from parliament_worker.http import SafeFetcher
from parliament_worker.models import SEOUL
from parliament_worker.processing import process_documents
from parliament_worker.publish import BackendPublisher
from parliament_worker.storage import LocalRawStore

LOGGER = logging.getLogger(__name__)


def parser() -> argparse.ArgumentParser:
    """Build bounded commands; all side effects require an explicit flag/path."""
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    from parliament_worker.knowledge.cli import add_parser

    add_parser(commands)
    from parliament_worker.law_cli import add_parser as add_law_parser

    add_law_parser(commands)
    from parliament_worker.roster.cli import add_parser as add_roster_parser

    add_roster_parser(commands)
    from parliament_worker.bill_cli import add_parser as add_bill_parser

    add_bill_parser(commands)
    from parliament_worker.graphrag.cli import add_parser as add_graphrag_parser

    add_graphrag_parser(commands)
    from parliament_worker.radar.cli import add_parser as add_radar_parser

    add_radar_parser(commands)
    collector = commands.add_parser("collect", help="read official public sources")
    collector.add_argument("--source", choices=sorted(SOURCES), required=True)
    collector.add_argument("--days", type=int, default=90)
    collector.add_argument("--max-pages", type=int, default=2)
    collector.add_argument("--max-records", type=int, default=30)
    collector.add_argument(
        "--output", type=Path, help="explicit local snapshot directory"
    )
    collector.add_argument(
        "--publish",
        action="store_true",
        help="import structural candidates as backend drafts",
    )
    collector.add_argument(
        "--s3",
        action="store_true",
        help="also preserve raw bytes in configured S3 bucket",
    )
    collector.add_argument(
        "--prepare-summary",
        action="store_true",
        help="explicit optional model request; local human-review drafts only",
    )
    collector.add_argument(
        "--summary-limit",
        type=int,
        default=3,
        help="maximum 1..3 drafts per explicit run",
    )
    relay = commands.add_parser(
        "relay-outbox", help="explicitly send a bounded SQS outbox batch"
    )
    relay.add_argument(
        "--send", action="store_true", help="required opt-in for DB/SQS writes"
    )
    relay.add_argument("--limit", type=int, default=20)
    inbox = commands.add_parser(
        "consume-versions", help="archive exact original versions from SQS"
    )
    inbox.add_argument(
        "--consume",
        action="store_true",
        help="required opt-in for SQS acknowledgements",
    )
    inbox.add_argument("--output", type=Path, required=True)
    mail = commands.add_parser(
        "mail", help="private email previews or explicit SES delivery"
    )
    mail.add_argument(
        "--output", type=Path, required=True, help="private EML spool directory"
    )
    mail.add_argument("--limit", type=int, default=20)
    mail.add_argument(
        "--send", action="store_true", help="explicit single-attempt SES delivery"
    )
    return result


def _write_report(path: Path, report: dict[str, Any]) -> None:
    """Save an atomic local run report; immutable raw snapshots live separately."""
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _collect(args: argparse.Namespace, options: argparse.ArgumentParser) -> int:
    """Collect sources and perform only explicitly requested output/imports."""
    if (args.publish or args.s3 or args.prepare_summary) and args.output is None:
        options.error(
            "--publish/--s3/--prepare-summary require --output for original evidence preservation"
        )
    if args.prepare_summary and args.publish:
        options.error("--prepare-summary cannot be combined with --publish")
    if args.prepare_summary and not os.environ.get("PARLIAMENT_REVIEW_LEDGER"):
        options.error(
            "--prepare-summary requires the shared PARLIAMENT_REVIEW_LEDGER path"
        )
    if not 1 <= args.summary_limit <= 3:
        options.error("--summary-limit must be 1..3")
    if args.publish and not (
        os.environ.get("TRACKING_ADMIN_KEY")
        or os.environ.get("PARLIAMENT_INGESTION_ADMIN_KEY")
    ):
        options.error("TRACKING_ADMIN_KEY or PARLIAMENT_INGESTION_ADMIN_KEY required")
    if args.s3 and not os.environ.get("PARLIAMENT_RAW_BUCKET"):
        options.error("PARLIAMENT_RAW_BUCKET required for --s3")
    fetcher = SafeFetcher()
    store = None
    publisher = None
    provider = None
    review_ledger = None
    try:
        if args.prepare_summary:
            from parliament_worker.provider import OpenAISummaryProvider
            from parliament_worker.review import ReviewLedger

            provider = OpenAISummaryProvider.from_env()
            try:
                budget = Decimal(
                    os.environ.get("PARLIAMENT_SUMMARY_MONTHLY_BUDGET_KRW", "100000")
                )
            except InvalidOperation as error:
                raise ValueError("invalid configured summary budget") from error
            review_ledger = ReviewLedger(
                Path(os.environ["PARLIAMENT_REVIEW_LEDGER"]), monthly_budget=budget
            )
        collected = collect(
            args.source,
            fetcher,
            datetime.now(SEOUL),
            max_pages=args.max_pages,
            days=args.days,
            max_records=args.max_records,
        )
        store = LocalRawStore(args.output) if args.output else None
        processed = process_documents(collected.documents, store=store)
        summary_paths = []
        if provider and review_ledger:
            from parliament_worker.summaries import prepare_summary

            eligible = {
                (event["id"], evidence["sourceVersion"])
                for event in processed.events
                for evidence in event["evidence"]
            }
            for document in collected.documents:
                if document_body_status(document) != "available":
                    continue
                if (
                    f"gov_{document.identity}",
                    document.payload_hash,
                ) not in eligible or len(summary_paths) >= args.summary_limit:
                    continue
                path = prepare_summary(
                    document,
                    provider,
                    review_ledger,
                    args.output,
                    document.collected_at,
                )
                summary_paths.append(str(path))
        imported = 0
        if args.publish:
            publisher = BackendPublisher.from_env()
            for event in processed.events:
                publisher.publish(event)
                imported += 1
        if args.s3:
            from parliament_worker.aws import S3RawStore

            cloud_store = S3RawStore(os.environ["PARLIAMENT_RAW_BUCKET"], enabled=True)
            for doc in collected.documents:
                cloud_store.save(doc.source_key, doc.record_key, doc.raw)
        report = {
            "source": args.source,
            "status": collected.status,
            "boundedPages": collected.pages,
            "windowDays": args.days,
            "dryRun": not args.publish,
            "importedDrafts": imported,
            "events": processed.events,
            "reviewQueue": processed.review_queue,
            "errors": collected.errors,
            "summaryDrafts": summary_paths,
        }
        if args.output:
            _write_report(args.output / "report.json", report)
        LOGGER.info(
            "Collected %s original versions; %s structural candidates; %s blocked; %s imported drafts; status=%s",
            len(collected.documents),
            len(processed.events),
            len(processed.review_queue),
            imported,
            collected.status,
        )
        return 1 if collected.errors else 0
    finally:
        fetcher.close()
        if publisher:
            publisher.close()
        if store:
            store.close()
        if provider:
            provider.close()
        if review_ledger:
            review_ledger.close()


def _queue(args: argparse.Namespace, options: argparse.ArgumentParser) -> int:
    """Run one explicitly enabled relay or version archival batch."""
    from parliament_worker.aws import SqsOutboxRelay, SqsVersionConsumer
    from parliament_worker.db import MySqlOutbox, connect_mysql

    if not getattr(args, "send", False) and not getattr(args, "consume", False):
        options.error("queue writes require --send or --consume")
    queue_url = os.environ.get("PARLIAMENT_PROCESSING_QUEUE_URL", "")
    if not queue_url:
        options.error("PARLIAMENT_PROCESSING_QUEUE_URL required")
    connection = connect_mysql()
    repository = MySqlOutbox(connection)
    try:
        if args.command == "relay-outbox":
            count = SqsOutboxRelay(repository, queue_url, enabled=True).run(args.limit)
            LOGGER.info("Dispatched %s original-version messages", count)
        else:
            from parliament_worker.versions import VersionArchive

            archive = VersionArchive(args.output, repository.version)
            consumer = SqsVersionConsumer(
                queue_url, args.output / "inbox.sqlite3", archive.process, enabled=True
            )
            try:
                count = consumer.run_once()
                LOGGER.info(
                    "Archived %s original versions; unsupported mappings remain explicit locally",
                    count,
                )
            finally:
                consumer.close()
    finally:
        connection.close()
    return 0


def _mail(args: argparse.Namespace, options: argparse.ArgumentParser) -> int:
    """Preview private mail by default; verified SES sender is operator configured."""
    from parliament_worker.db import connect_mysql
    from parliament_worker.mail import MailComposer, PrivateSpool, SesMailer
    from parliament_worker.mail_db import MySqlMailOutbox

    if not 1 <= args.limit <= 100:
        options.error("--limit must be 1..100")
    sender = os.environ.get("PARLIAMENT_MAIL_FROM")
    if args.send and not sender:
        options.error("PARLIAMENT_MAIL_FROM requires an operator-verified SES sender")
    composer = MailComposer(
        sender or "preview@parliament.invalid",
        os.environ.get("TRACKING_PUBLIC_BASE_URL", "http://localhost:3000"),
    )
    spool = PrivateSpool(args.output / "delivery" if args.send else args.output)
    mailer = SesMailer(enabled=True) if args.send else None
    connection = connect_mysql()
    try:
        counts = MySqlMailOutbox(connection).run(
            composer,
            spool,
            datetime.now(SEOUL),
            limit=args.limit,
            mailer=mailer,
            clock=lambda: datetime.now(SEOUL),
        )
        LOGGER.info("Mail batch counts=%s; private payloads are omitted", counts)
        return 1 if counts.get("uncertain") else 0
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    """Run the worker without logging secrets or sending unsolicited notifications."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    options = parser()
    args = options.parse_args(argv)
    try:
        if args.command == "radar":
            from parliament_worker.radar.cli import run

            return run(args, options)
        if args.command == "graphrag":
            from parliament_worker.graphrag.cli import run

            return run(args, options)
        if args.command == "roster":
            from parliament_worker.roster.cli import run

            return run(args, options)
        if args.command == "bills":
            from parliament_worker.bill_cli import run

            return run(args, options)
        if args.command == "law":
            from parliament_worker.law_cli import run

            return run(args, options)
        if args.command == "pilot":
            from parliament_worker.knowledge.cli import run

            return run(args, options)
        if args.command == "collect":
            return _collect(args, options)
        if args.command == "mail":
            return _mail(args, options)
        return _queue(args, options)
    except Exception as error:
        location = " > ".join(
            f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}"
            for frame in traceback.extract_tb(error.__traceback__)[-4:]
        )
        LOGGER.error(
            "Worker failed (%s) at %s; originals remain preserved",
            type(error).__name__,
            location,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
