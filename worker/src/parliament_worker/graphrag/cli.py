"""Explicit private commands and a continuous, independently stoppable factory."""

import argparse
import fcntl
import json
import logging
import os
import signal
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from parliament_worker.graphrag.client import (
    InferenceClient,
    InferenceConfig,
    InferenceError,
)
from parliament_worker.graphrag.engine import Factory
from parliament_worker.graphrag.index import current_artifacts, graph_view
from parliament_worker.graphrag.query import question_status, submit_question
from parliament_worker.graphrag.recovery import drain_unknown_acceptance
from parliament_worker.graphrag.store import GraphStore
from parliament_worker.knowledge.files import private_write

LOGGER = logging.getLogger(__name__)


def add_parser(commands: Any) -> None:
    """Register commands without granting model/publication side effects by default."""
    command = commands.add_parser(
        "graphrag", help="private evidence-backed graph inference factory"
    )
    actions = command.add_subparsers(dest="graphrag_action", required=True)
    for name in (
        "work",
        "status",
        "ask",
        "export",
        "review-batch",
        "resume",
        "audit-office",
        "audit-coverage",
        "audit-claims",
        "audit-answer",
    ):
        action = actions.add_parser(name)
        action.add_argument("--state", type=Path, required=True)
        if name in {
            "status",
            "ask",
            "export",
            "review-batch",
            "audit-office",
            "audit-coverage",
            "audit-claims",
            "audit-answer",
        }:
            action.add_argument("--output", type=Path, required=name != "status")
        if name in {"audit-office", "review-batch"}:
            action.add_argument("--input", type=Path, action="append", required=True)
        if name == "audit-answer":
            action.add_argument("--question-id", required=True)
        if name == "work":
            action.add_argument("--input", type=Path, action="append", required=True)
            action.add_argument("--send", action="store_true")
            action.add_argument(
                "--retry-output-failures",
                action="store_true",
                help="keep retrying eligible failed outputs while preserving earlier attempts",
            )
            action.add_argument("--forever", action="store_true")
            action.add_argument(
                "--retire-missing",
                action="store_true",
                help="retire absent scopes after a complete successful input scan",
            )
            action.add_argument("--concurrency", type=int, default=1)
            action.add_argument(
                "--daily-jobs",
                type=int,
                default=500,
                help="UTC-day new-request limit; 0 disables it",
            )
            action.add_argument(
                "--daily-tokens",
                type=int,
                default=2_000_000,
                help="UTC-day reserved-token limit; 0 disables it",
            )
            action.add_argument("--queue-capacity", type=int, default=256)
            action.add_argument("--poll-seconds", type=float, default=3)
            action.add_argument("--scan-seconds", type=float, default=60)
            action.add_argument("--plan-seconds", type=float, default=5)
            action.add_argument("--max-operations", type=int, default=4)
            action.add_argument("--api-port", type=int)
        elif name == "ask":
            action.add_argument("--question", required=True)
            action.add_argument("--mode", choices=("local", "global"), default="local")
            action.add_argument("--entity-id")
            action.add_argument("--wait-seconds", type=float, default=0)


def _model_signature() -> str:
    """Require an actual observed revision; model alias alone is not a cache key."""
    actual = os.environ.get("GRAPHRAG_MODEL_REPO", "")
    revision = os.environ.get("GRAPHRAG_MODEL_REVISION", "")
    if not actual or not revision or len(actual) > 256 or len(revision) > 128:
        raise ValueError("configure verified GraphRAG model repository and revision")
    return actual + "@" + revision


def _save(path: Path, value: Any) -> None:
    private_write(
        path,
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode(),
        immutable=False,
    )


@contextmanager
def _worker_lock(root: Path) -> Iterator[None]:
    """One executor owns each state directory; readers/questions remain concurrent."""
    descriptor = os.open(
        root / ".factory.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600
    )
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("GraphRAG executor already active") from None
        yield
    finally:
        os.close(descriptor)


def _work(args: argparse.Namespace, store: GraphStore) -> int:
    if (
        not 1 <= args.max_operations <= 64
        or not 5 <= args.scan_seconds <= 3600
        or not 1 <= args.plan_seconds <= 3600
    ):
        raise ValueError("invalid factory loop limits")
    client = InferenceClient(InferenceConfig.from_env()) if args.send else None
    stopped = threading.Event()
    old_handlers = {}
    api, api_thread = None, None
    try:
        signature = _model_signature()
        factory = Factory(
            store,
            client,
            signature,
            concurrency=args.concurrency,
            daily_jobs=args.daily_jobs,
            daily_tokens=args.daily_tokens,
            queue_capacity=args.queue_capacity,
            poll_seconds=args.poll_seconds,
            retry_output_failures=getattr(args, "retry_output_failures", False),
        )
        for signum in (signal.SIGINT, signal.SIGTERM):
            old_handlers[signum] = signal.signal(
                signum, lambda _signal, _frame: stopped.set()
            )
        with _worker_lock(store.root):
            factory.recover_projections()
            if args.api_port is not None:
                from parliament_worker.graphrag.api import create_server

                api = create_server(
                    store,
                    os.environ.get("GRAPHRAG_API_TOKEN", ""),
                    signature,
                    port=args.api_port,
                )
                api_thread = threading.Thread(target=api.serve_forever, daemon=True)
                api_thread.start()
            _save(
                store.root / "executor.json",
                {
                    "pid": os.getpid(),
                    "startedAt": time.time(),
                    "mode": "send" if args.send else "plan",
                    "apiPort": args.api_port,
                },
            )
            scanned, last_log, recovery_checked = 0.0, 0.0, 0.0
            planned_at = None
            while not stopped.is_set():
                now = time.monotonic()
                scan_seconds = 0.0
                if now - scanned >= args.scan_seconds:
                    try:
                        changes = factory.sync_inputs(
                            args.input, retire_missing=args.retire_missing
                        )
                        scanned = now
                        scan_seconds = time.monotonic() - now
                        if any(changes.values()):
                            LOGGER.info("GraphRAG source changes=%s", changes)
                            planned_at = None
                    except (ValueError, OSError):
                        # A failed scan never implies source deletion and does not
                        # allow inference against a possibly outdated input set.
                        LOGGER.error("GraphRAG input scan failed; inference deferred")
                        if not args.forever:
                            return 1
                        stopped.wait(min(60, args.scan_seconds))
                        continue
                if stopped.is_set():
                    break
                if (
                    client
                    and (factory._paused() or recovery_checked == 0.0)
                    and now - recovery_checked >= 60
                ):
                    recovery_checked = now
                    try:
                        recovered = drain_unknown_acceptance(
                            store, client, signature, limit=args.concurrency
                        )
                        if recovered:
                            LOGGER.info(
                                "GraphRAG original acceptance identities recovered count=%s",
                                recovered,
                            )
                            # Continue immediately if more than one bounded pass
                            # is needed for the persisted unknown-acceptance backlog.
                            recovery_checked = 0.0
                    except InferenceError as error:
                        LOGGER.warning(
                            "GraphRAG acceptance recovery deferred category=%s", error
                        )
                planning = time.monotonic()
                planned, plan_seconds = {}, 0.0
                if planned_at is None or planning - planned_at >= args.plan_seconds:
                    try:
                        planned = factory.plan()
                    except ValueError as error:
                        if str(error) != "pilot store busy" or not args.forever:
                            raise
                        LOGGER.warning("GraphRAG planning deferred while store is busy")
                        stopped.wait(min(5, args.plan_seconds))
                        continue
                    planned_at = time.monotonic()
                    plan_seconds = planned_at - planning
                if stopped.is_set():
                    break
                executing = time.monotonic()
                operations = factory.tick(args.max_operations) if client else 0
                tick_seconds = time.monotonic() - executing
                if now - last_log >= 30 or not args.forever:
                    LOGGER.info(
                        "GraphRAG planned=%s operations=%s status=%s "
                        "scan_seconds=%.3f plan_seconds=%.3f tick_seconds=%.3f",
                        planned,
                        operations,
                        store.status(),
                        scan_seconds,
                        plan_seconds,
                        tick_seconds,
                    )
                    _save(
                        store.root / "status.json",
                        {
                            **store.status(),
                            "updatedAt": time.time(),
                            "paused": factory._paused(),
                        },
                    )
                    last_log = now
                if not args.forever:
                    return 0
                stopped.wait(
                    args.poll_seconds if operations else max(60, args.poll_seconds)
                )
        return 0
    finally:
        if api:
            api.shutdown()
            api.server_close()
        if api_thread:
            api_thread.join(timeout=5)
        if client:
            client.close()
        for signum, handler in old_handlers.items():
            signal.signal(signum, handler)


def run(args: argparse.Namespace, options: argparse.ArgumentParser) -> int:
    """Execute the requested private operation, never send mail or approve people."""
    store = GraphStore(args.state)
    try:
        if args.graphrag_action == "work":
            if args.forever and not args.send:
                options.error("continuous remote execution requires --send")
            return _work(args, store)
        if args.graphrag_action == "resume":
            store.invalidate_artifact("control", "pause")
            LOGGER.info("GraphRAG pause cleared; persisted requests remain unchanged")
        elif args.graphrag_action == "ask":
            if not 0 <= args.wait_seconds <= 300:
                options.error("--wait-seconds must be 0..300")
            request = submit_question(
                store,
                args.question,
                args.mode,
                _model_signature(),
                entity_id=args.entity_id,
            )
            deadline = time.monotonic() + args.wait_seconds
            while request["state"] == "queued" and time.monotonic() < deadline:
                time.sleep(1)
                request = question_status(store, request["id"])
            _save(args.output, request)
            LOGGER.info("Private GraphRAG question state=%s", request["state"])
        elif args.graphrag_action == "status":
            status = store.status()
            if args.output:
                _save(args.output, status)
            LOGGER.info("GraphRAG status=%s", status)
        elif args.graphrag_action == "export":
            graphs = current_artifacts(store, "graph")
            _save(
                args.output,
                {
                    "schema": "parliament-graphrag-review-v1",
                    "public": False,
                    "note": "General links can be machine-approved; identity/source-use/publication gates still apply. Personal actions and new identities require review. This file is not a public KnowledgeBatch.",
                    "sourceRevisions": [
                        {k: source[k] for k in ("scope", "fingerprint", "generation")}
                        for source in store.sources()
                    ],
                    "candidateGraphs": graphs,
                    "communities": current_artifacts(store, "community"),
                    "coverage": graph_view(store)["coverage"],
                },
            )
            LOGGER.info("Exported private GraphRAG review artifacts")
        elif args.graphrag_action == "review-batch":
            from parliament_worker.graphrag.review_bridge import merge_review_batch
            from parliament_worker.knowledge.review import read_batch

            if len(args.input) != 1:
                options.error("review-batch requires exactly one --input")
            packet = merge_review_batch(
                read_batch(args.input[0]), store.query_snapshot()
            )
            private_write(
                args.output,
                json.dumps(
                    packet, ensure_ascii=False, sort_keys=True, indent=2
                ).encode(),
            )
            LOGGER.info(
                "Private GraphRAG review batch prepared relations=%s evidence=%s",
                len(packet["relations"]),
                len(packet["evidence"]),
            )
        elif args.graphrag_action == "audit-office":
            from parliament_worker.graphrag.office_audit import audit_office_edges

            report = audit_office_edges(store, args.input)
            _save(args.output, report)
            LOGGER.info(
                "Office candidate audit total=%s requires_review=%s",
                report["totalOfficeEdges"],
                report["reviewRequired"],
            )
        elif args.graphrag_action == "audit-coverage":
            from parliament_worker.graphrag.coverage import audit_coverage

            report = audit_coverage(store.query_snapshot())
            _save(args.output, report)
            LOGGER.info(
                "GraphRAG structural coverage source_units=%s missing_graphs=%s "
                "missing_leaves=%s",
                report["sourceUnits"],
                report["missingSourceGraphs"],
                report["missingLeaves"],
            )
        elif args.graphrag_action == "audit-claims":
            from parliament_worker.graphrag.claim_quality_audit import (
                audit_claim_quality,
            )

            report = audit_claim_quality(store.query_snapshot())
            _save(args.output, report)
            LOGGER.info(
                "Private claim quality audit claims=%s review_cases=%s",
                report["counts"]["claims"],
                len(report["cases"]),
            )
        elif args.graphrag_action == "audit-answer":
            from parliament_worker.graphrag.answer_audit import audit_question

            report = audit_question(store, args.question_id)
            _save(args.output, report)
            LOGGER.info(
                "Private question audit maps=%s/%s structural=%s editorial=%s",
                report["mapJobs"]["completed"],
                report["mapJobs"]["total"],
                len(report["structuralFindings"]),
                len(report["editorialFindings"]),
            )
        return 0
    finally:
        store.close()
