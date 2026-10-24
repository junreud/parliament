"""Explicit current-roster collection, preparation and authenticated draft import."""

import argparse
import hashlib
import json
import logging
import os
import ssl
import sys
from pathlib import Path
from typing import Any

import httpx
import truststore

from parliament_worker.http import SafeFetcher
from parliament_worker.knowledge.files import private_read, private_write
from parliament_worker.knowledge.review import KnowledgePublisher, read_batch
from parliament_worker.roster.batches import candidate_batches
from parliament_worker.roster.collection import collect_roster

LOGGER = logging.getLogger(__name__)


def _official_source_client() -> httpx.Client:
    """Keep certificate checks while using macOS chain recovery for sources.

    Returns:
        A verified HTTP client honoring explicitly configured CA paths.
    """
    headers = {"User-Agent": "Mozilla/5.0"}
    if sys.platform == "darwin" and not (
        os.environ.get("SSL_CERT_FILE") or os.environ.get("SSL_CERT_DIR")
    ):
        return httpx.Client(
            headers=headers, verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        )
    return httpx.Client(headers=headers)


def add_parser(commands: Any) -> None:
    """Register bounded roster commands, keeping draft import explicit."""
    roster = commands.add_parser(
        "roster", help="collect current official person rosters"
    )
    actions = roster.add_subparsers(dest="roster_action", required=True)
    collect = actions.add_parser("collect")
    collect.add_argument("--manifest", type=Path, required=True)
    collect.add_argument("--output", type=Path, required=True)
    collect.add_argument("--job-id", required=True)
    collect.add_argument("--source", help="one manifest source, otherwise all sources")
    prepare = actions.add_parser("prepare")
    prepare.add_argument("--records", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--identity-map", type=Path)
    profiles = actions.add_parser("profiles")
    profiles.add_argument("--manifest", type=Path, required=True)
    profiles.add_argument("--output", type=Path, required=True)
    profiles.add_argument("--job-id", required=True)
    office_table = actions.add_parser("office-table")
    office_table.add_argument("--manifest", type=Path, required=True)
    office_table.add_argument("--graph-state", type=Path, required=True)
    office_table.add_argument("--output", type=Path, required=True)
    office_table.add_argument("--job-id", required=True)
    graph = actions.add_parser("stage-graph")
    graph.add_argument("--previous-run", type=Path, required=True)
    graph.add_argument("--current-run", type=Path, required=True)
    graph.add_argument("--graph-input", type=Path, required=True)
    graph.add_argument("--report", type=Path, required=True)
    graph.add_argument("--identity-map", type=Path)
    profile_graph = actions.add_parser("stage-profiles-graph")
    profile_graph.add_argument("--previous-run", type=Path, required=True)
    profile_graph.add_argument("--current-run", type=Path, required=True)
    profile_graph.add_argument("--graph-input", type=Path, required=True)
    profile_graph.add_argument("--graph-state", type=Path)
    profile_graph.add_argument("--report", type=Path, required=True)
    profile_graph.add_argument("--identity-map", type=Path)
    imported = actions.add_parser("import")
    imported.add_argument("--index", type=Path, required=True)
    imported.add_argument("--import", dest="import_enabled", action="store_true")


def _read(path: Path, limit: int = 20_000_000) -> Any:
    """Read explicit bounded private inputs without symlink traversal."""
    return json.loads(private_read(path, max_bytes=limit))


def _save(path: Path, value: Any) -> None:
    """Persist private immutable artifacts; replay never overwrites a prior run."""
    private_write(
        path, json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode()
    )


def _save_import_receipt(path: Path, value: dict[str, Any]) -> None:
    """Keep the first acknowledgement and append changed replay outcomes privately."""
    if path.exists():
        if _read(path) == value:
            return
        digest = hashlib.sha256(
            json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        path = path.with_name(path.stem + ".replay-" + digest + ".json")
    _save(path, value)


def run(args: argparse.Namespace, options: argparse.ArgumentParser) -> int:
    """Execute a current-source run without publishing candidates or sending mail."""
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if args.roster_action == "stage-graph":
        from parliament_worker.roster.graph_refresh import (
            plan_refresh,
            stage_refresh,
            validate_run_pair,
        )

        previous = _read(args.previous_run / "records.json")
        previous_coverage = _read(args.previous_run / "coverage.json")
        current = _read(args.current_run / "records.json")
        current_coverage = _read(args.current_run / "coverage.json")
        validate_run_pair(previous, previous_coverage, current, current_coverage)
        plan = plan_refresh(previous, current, complete=True)
        mapping = _read(args.identity_map, 2_000_000) if args.identity_map else {}
        staged = stage_refresh(plan, args.graph_input, mapping)
        _save(
            args.report,
            {
                "schema": "parliament-roster-graph-refresh-v1",
                "previousCount": plan["previousCount"],
                "currentCount": plan["currentCount"],
                "unchanged": plan["unchanged"],
                "stagedRecordCount": len(plan["stage"]),
                "stagedBatchFiles": [path.name for path in staged],
                "identityReview": plan["identityReview"],
                "removedForReview": plan["removedForReview"],
                "publication": "pending_operator_review",
            },
        )
        LOGGER.info(
            "Staged %s private roster candidates; %s identities and %s removals require review",
            len(plan["stage"]),
            len(plan["identityReview"]),
            len(plan["removedForReview"]),
        )
        return 0
    if args.roster_action == "stage-profiles-graph":
        from parliament_worker.roster.graph_refresh import (
            _existing_identity_map,
            backfill_ungrounded_profiles,
            plan_profile_refresh,
            stage_refresh,
        )

        previous = _read(args.previous_run / "profiles.json")
        current = _read(args.current_run / "profiles.json")
        plan = plan_profile_refresh(previous, current)
        mapping = _read(args.identity_map, 2_000_000) if args.identity_map else {}
        if args.graph_state:
            from parliament_worker.graphrag.store import GraphStore

            if not (args.graph_state / "graph.sqlite3").is_file():
                raise ValueError(
                    "existing graph state is required for profile backfill"
                )
            graph_sources = GraphStore(args.graph_state).sources()
            plan = backfill_ungrounded_profiles(plan, current, graph_sources)
            for key, value in _existing_identity_map(graph_sources).items():
                if key in mapping and mapping[key] != value:
                    raise ValueError("verified identity conflicts with graph state")
                mapping[key] = value
        staged = stage_refresh(plan, args.graph_input, mapping)
        _save(
            args.report,
            {
                "schema": "parliament-profile-graph-refresh-v1",
                "priorSuccessfulCount": len(previous["records"]),
                "currentSuccessfulCount": len(current["records"]),
                "stagedRecordCount": len(plan["stage"]),
                "backfilledCount": plan.get("backfilledCount", 0),
                "unavailableForGraph": plan.get("unavailableForGraph", []),
                "stagedBatchFiles": [path.name for path in staged],
                "identityReview": plan["identityReview"],
                "removedForReview": plan["removedForReview"],
                "sourceFailures": plan["sourceFailures"],
                "publication": "pending_operator_review",
            },
        )
        LOGGER.info(
            "Staged %s private office profiles; %s source observations remain unresolved",
            len(plan["stage"]),
            len(plan["sourceFailures"]),
        )
        return 0
    if args.roster_action == "office-table":
        from parliament_worker.graphrag.store import GraphStore
        from parliament_worker.roster.office_table import collect_office_table

        if not (args.graph_state / "graph.sqlite3").is_file():
            raise ValueError("existing graph state is required for office table IDs")
        fetcher = SafeFetcher(
            client=_official_source_client(),
            max_bytes=10_000_000,
            timeout=30,
            total_timeout=60,
        )
        try:
            result = collect_office_table(
                _read(args.manifest, 2_000_000),
                fetcher,
                args.output,
                args.job_id,
                existing_sources=GraphStore(args.graph_state).sources(),
            )
        finally:
            fetcher.close()
        _save(args.output / "runs" / args.job_id / "records.json", result["records"])
        LOGGER.info(
            "Collected %s source-local office table rows", len(result["records"])
        )
        return 0
    if args.roster_action == "profiles":
        from parliament_worker.roster.profiles import collect_profiles

        manifest = _read(args.manifest, 2_000_000)
        fetcher = SafeFetcher(
            client=_official_source_client(),
            max_bytes=10_000_000,
            timeout=30,
            total_timeout=60,
        )
        try:
            result = collect_profiles(
                manifest["profiles"], fetcher, args.output, args.job_id, delay=0.35
            )
        finally:
            fetcher.close()
        _save(args.output / "runs" / args.job_id / "records.json", result["records"])
        LOGGER.info(
            "Refreshed %s office candidates; %s observations require review",
            len(result["records"]),
            sum(o["status"] != "success" for o in result["observations"]),
        )
        return 0 if result["complete"] else 1
    if args.roster_action == "collect":
        manifest = _read(args.manifest, 1_000_000)
        sources = manifest.get("sources")
        if not isinstance(sources, list) or not 1 <= len(sources) <= 100:
            raise ValueError("invalid roster manifest")
        selected = [s for s in sources if not args.source or s["id"] == args.source]
        if not selected:
            raise ValueError("unknown roster source")
        client = _official_source_client()
        fetcher = SafeFetcher(
            client=client, max_bytes=10_000_000, timeout=30, total_timeout=60
        )
        try:
            results = [
                collect_roster(source, fetcher, args.output, args.job_id, delay=0.35)
                for source in selected
            ]
        finally:
            fetcher.close()
        _save(
            args.output / "runs" / args.job_id / "records.json",
            [record for result in results for record in result["records"]],
        )
        _save(
            args.output / "runs" / args.job_id / "coverage.json",
            [
                {key: value for key, value in result.items() if key != "records"}
                for result in results
            ],
        )
        LOGGER.info(
            "Collected %s current roster candidates across %s sources; %s complete",
            sum(r["recordCount"] for r in results),
            len(results),
            sum(r["complete"] for r in results),
        )
        return 0 if all(result["complete"] for result in results) else 1
    if args.roster_action == "prepare":
        records = _read(args.records)
        if not isinstance(records, list) or len(records) > 20000:
            raise ValueError("invalid roster records")
        mapping = _read(args.identity_map, 2_000_000) if args.identity_map else {}
        batches = candidate_batches(records, mapping)
        entries = []
        for batch in batches:
            filename = batch["id"] + ".json"
            _save(args.output / filename, batch)
            entries.append(filename)
        _save(
            args.output / "index.json",
            {
                "batches": entries,
                "people": len(records),
                "publication": "pending_operator_review",
            },
        )
        LOGGER.info(
            "Prepared %s bounded candidate batches; identity and usage review remain pending",
            len(batches),
        )
        return 0
    if not args.import_enabled:
        options.error("roster import requires --import (drafts only)")
    index = _read(args.index, 1_000_000)
    names = index.get("batches", [])
    if not isinstance(names, list) or len(names) > 500:
        raise ValueError("invalid candidate batch index")
    publisher = KnowledgePublisher.from_env()
    try:
        for name in names:
            if (
                not isinstance(name, str)
                or Path(name).name != name
                or not name.endswith(".json")
            ):
                raise ValueError("invalid batch index filename")
            batch = read_batch(args.index.parent / name)
            response = publisher.import_batch(batch)
            _save_import_receipt(args.index.parent / (name + ".receipt.json"), response)
    finally:
        publisher.close()
    LOGGER.info(
        "Imported %s candidate batches; no public approval requested", len(names)
    )
    return 0
