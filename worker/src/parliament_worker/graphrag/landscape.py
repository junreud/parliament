"""Loopback-only, read-only explorer for local collection and GraphRAG state."""

import argparse
import json
import logging
import re
import sqlite3
import threading
from collections import Counter, defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .landscape_catalog import DOMAINS, PAGE_SIZE, domain_for_key
from .landscape_collection import collection_summary
from .landscape_radar import radar_summary

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[4]
ASSETS = Path(__file__).with_name("landscape_ui")
DEFAULT_DB = ROOT / ".local/graphrag/state/graph.sqlite3"
DEFAULT_MYSQL = ROOT / ".local/data-landscape/mysql-snapshot.json"
_CONTACT = re.compile(
    r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|01[016789][ -]?\d{3,4}[ -]?\d{4}"
)
_HOST = re.compile(r"(?:127\.0\.0\.1|localhost)(?::\d{1,5})?")


def _redact(value: str, limit: int = 1600) -> str:
    """Omit likely contact details from operator snippets."""
    return _CONTACT.sub("[연락처 생략]", value[:limit])


def _source_url(raw: Any) -> str | None:
    """Return only HTTPS links without credential-looking query parameters."""
    if not isinstance(raw, str) or len(raw) > 2000:
        return None
    parsed = urlsplit(raw)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username:
        return None
    blocked = {
        "key",
        "apikey",
        "api_key",
        "servicekey",
        "auth",
        "token",
        "oc",
        "password",
        "secret",
    }
    if any(
        part.split("=", 1)[0].lower() in blocked for part in parsed.query.split("&")
    ):
        return None
    return raw


class LandscapeRepository:
    """Read an atomic GraphRAG SQLite revision without changing its state."""

    def __init__(self, db_path: Path, mysql_path: Path | None = None) -> None:
        self.db_path = db_path.resolve()
        self.mysql_path = mysql_path.resolve() if mysql_path else None
        self._lock = threading.Lock()
        self._cached: dict[str, Any] | None = None
        self._signature: tuple[int, int] | None = None

    def _connect(self) -> sqlite3.Connection:
        if not self.db_path.is_file():
            raise FileNotFoundError("GraphRAG state is unavailable")
        db = sqlite3.connect(self.db_path.as_uri() + "?mode=ro", uri=True, timeout=3)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        return db

    def _mysql(self) -> dict[str, Any] | None:
        if not self.mysql_path or not self.mysql_path.is_file():
            return None
        try:
            data = json.loads(self.mysql_path.read_text(encoding="utf-8"))
            return (
                data if data.get("schema") == "parliament-mysql-landscape-v1" else None
            )
        except (OSError, ValueError):
            return None

    def overview(self) -> dict[str, Any]:
        """Compute counts from one read transaction and cache by file revision."""
        stat = self.db_path.stat()
        signature = (stat.st_mtime_ns, stat.st_size)
        with self._lock:
            if self._cached is None or signature != self._signature:
                self._cached = self._compute_overview()
                self._signature = signature
            return {
                **self._cached,
                "mysql": self._mysql(),
                "radar": radar_summary(ROOT),
                "collection": collection_summary(ROOT),
            }

    def _compute_overview(self) -> dict[str, Any]:
        source_keys: Counter[str] = Counter()
        source_units: Counter[str] = Counter()
        licenses: Counter[str] = Counter()
        body_statuses: Counter[str] = Counter()
        expected_graphs: set[str] = set()
        graph_source: dict[str, str] = {}
        nodes: dict[str, dict[str, Any]] = {}
        edges: dict[str, dict[str, Any]] = {}
        graph_keys: set[str] = set()
        report_levels: Counter[str] = Counter()
        report_groups = 0
        report_claims = 0
        with self._connect() as db:
            db.execute("BEGIN")
            for row in db.execute("SELECT scope,payload FROM sources WHERE active=1"):
                payload = json.loads(row["payload"])
                key = str(
                    payload.get("document", {}).get("sourceKey")
                    or row["scope"].split(":", 1)[0]
                )
                source_keys[key] += 1
                units = payload.get("units", [])
                source_units[key] += len(units)
                document = payload.get("document", {})
                licenses[str(document.get("licenseStatus") or "unknown")] += 1
                body_statuses[str(document.get("bodyStatus") or "unknown")] += 1
                for unit in units:
                    if isinstance(unit, dict) and isinstance(unit.get("id"), str):
                        graph_source[f"{row['scope']}:{unit['id']}"] = key
            for row in db.execute(
                "SELECT kind,artifact_key,payload FROM artifacts "
                "WHERE current=1 AND kind IN ('graph','community')"
            ):
                payload = json.loads(row["payload"])
                if row["kind"] == "graph":
                    graph_keys.add(row["artifact_key"])
                    for node in payload.get("nodes", []):
                        if isinstance(node, dict) and isinstance(node.get("id"), str):
                            nodes[node["id"]] = node
                    for edge in payload.get("edges", []):
                        if isinstance(edge, dict) and isinstance(edge.get("id"), str):
                            edges[edge["id"]] = edge
                else:
                    level = str(payload.get("level", "unknown"))
                    report_levels[level] += 1
                    groups = payload.get("groups", [])
                    report_groups += len(groups)
                    report_claims += sum(
                        len(group.get("claims", [])) for group in groups
                    )
            answers = db.execute(
                "SELECT COUNT(*) FROM artifacts WHERE current=1 AND kind='answer'"
            ).fetchone()[0]
            observed_at = db.execute(
                "SELECT MAX(last_observed_at) FROM source_observation_times"
            ).fetchone()[0]
            db.execute("COMMIT")
        expected_graphs = set(graph_source)
        indexed = expected_graphs & graph_keys
        indexed_by_source = Counter(graph_source[key] for key in indexed)
        domains = []
        for domain in DOMAINS:
            keys = domain["keys"]
            domains.append(
                {
                    **domain,
                    "sources": sum(source_keys[key] for key in keys),
                    "units": sum(source_units[key] for key in keys),
                    "graphs": sum(indexed_by_source[key] for key in keys),
                }
            )
        known = {key for domain in DOMAINS for key in domain["keys"]}
        domains.append(
            {
                "id": "other",
                "label": "기타 출처",
                "purpose": "계획 분류에 아직 연결하지 않은 현행 입력",
                "keys": sorted(set(source_keys) - known),
                "next": "원천 계약과 수집 목적 분류",
                "plan": "docs/data/graphrag-factory-runbook.md",
                "sources": sum(n for key, n in source_keys.items() if key not in known),
                "units": sum(n for key, n in source_units.items() if key not in known),
                "graphs": sum(
                    n for key, n in indexed_by_source.items() if key not in known
                ),
            }
        )
        return {
            "schema": "parliament-data-landscape-v1",
            "classification": "private_local_candidate",
            "databaseModifiedAt": self.db_path.stat().st_mtime,
            "latestSourceObservation": observed_at,
            "totals": {
                "sources": sum(source_keys.values()),
                "sourceUnits": len(expected_graphs),
                "indexedSourceUnits": len(indexed),
                "missingSourceGraphs": len(expected_graphs - graph_keys),
                "derivedGraphs": len(graph_keys - expected_graphs),
                "entities": len(nodes),
                "relations": len(edges),
                "reports": sum(report_levels.values()),
                "reportGroups": report_groups,
                "reportClaims": report_claims,
                "privateAnswers": answers,
            },
            "domains": domains,
            "sourceKeys": dict(source_keys.most_common()),
            "nodeKinds": dict(
                Counter(str(n.get("kind", "unknown")) for n in nodes.values())
            ),
            "edgeTypes": dict(
                Counter(str(e.get("type", "unknown")) for e in edges.values())
            ),
            "edgeDecisions": dict(
                Counter(str(e.get("decision", "unknown")) for e in edges.values())
            ),
            "reportLevels": dict(report_levels),
            "licenses": dict(licenses),
            "bodyStatuses": dict(body_statuses),
            "plans": [
                "docs/data/source-contracts.md",
                "docs/data/current-politicians-sources.md",
                "docs/plans/2026-10-13-graphrag-factory.md",
                "docs/data/knowledge-contract.md",
            ],
        }

    def sources(self, domain: str, query: str, page: int) -> dict[str, Any]:
        """Search bounded current records without loading raw content in bulk."""
        if page < 1 or page > 10000 or len(query) > 100:
            raise ValueError("invalid search")
        selected = next((d for d in DOMAINS if d["id"] == domain), None)
        if domain not in {"all", "other"} and selected is None:
            raise ValueError("invalid domain")
        clauses = ["active=1"]
        params: list[Any] = []
        if selected:
            clauses.append(
                "json_extract(payload,'$.document.sourceKey') IN ("
                + ",".join("?" for _ in selected["keys"])
                + ")"
            )
            params.extend(selected["keys"])
        elif domain == "other":
            known = [key for item in DOMAINS for key in item["keys"]]
            clauses.append(
                "json_extract(payload,'$.document.sourceKey') NOT IN ("
                + ",".join("?" for _ in known)
                + ")"
            )
            params.extend(known)
        if query:
            clauses.append(
                "(scope LIKE ? ESCAPE '\\' OR json_extract(payload,'$.document.title') LIKE ? ESCAPE '\\')"
            )
            needle = (
                "%"
                + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                + "%"
            )
            params.extend([needle, needle])
        where = " AND ".join(clauses)
        with self._connect() as db:
            total = db.execute(
                "SELECT COUNT(*) FROM sources WHERE " + where, params
            ).fetchone()[0]
            rows = db.execute(
                "SELECT scope,payload FROM sources WHERE "
                + where
                + " ORDER BY scope LIMIT ? OFFSET ?",
                [*params, PAGE_SIZE, (page - 1) * PAGE_SIZE],
            ).fetchall()
        items = []
        for row in rows:
            payload = json.loads(row["payload"])
            doc = payload.get("document", {})
            items.append(
                {
                    "scope": row["scope"],
                    "title": doc.get("title") or row["scope"],
                    "sourceKey": doc.get("sourceKey"),
                    "domain": domain_for_key(str(doc.get("sourceKey", ""))),
                    "units": len(payload.get("units", [])),
                    "license": doc.get("licenseStatus", "unknown"),
                    "bodyStatus": doc.get("bodyStatus", "unknown"),
                }
            )
        return {"items": items, "total": total, "page": page, "pageSize": PAGE_SIZE}

    def source(self, scope: str, offset: int) -> dict[str, Any] | None:
        """Inspect one source revision and a page of its graph-backed units."""
        if not 1 <= len(scope) <= 512 or offset < 0 or offset > 10000:
            raise ValueError("invalid source")
        with self._connect() as db:
            row = db.execute(
                "SELECT scope,fingerprint,generation,payload FROM sources "
                "WHERE active=1 AND scope=?",
                (scope,),
            ).fetchone()
            if row is None:
                return None
            payload = json.loads(row["payload"])
            units = payload.get("units", [])
            selected = units[offset : offset + 8]
            results = []
            for unit in selected:
                graph_row = db.execute(
                    "SELECT payload FROM artifacts WHERE kind='graph' AND current=1 "
                    "AND artifact_key=? ORDER BY sequence DESC LIMIT 1",
                    (f"{scope}:{unit['id']}",),
                ).fetchone()
                graph = json.loads(graph_row["payload"]) if graph_row else {}
                names = {n.get("id"): n.get("name") for n in graph.get("nodes", [])}
                results.append(
                    {
                        "id": unit.get("id"),
                        "locator": unit.get("locator"),
                        "text": _redact(str(unit.get("text", ""))),
                        "textTruncated": len(str(unit.get("text", ""))) > 1600,
                        "indexed": graph_row is not None,
                        "entities": [
                            {
                                "id": n.get("id"),
                                "name": n.get("name"),
                                "kind": n.get("kind"),
                            }
                            for n in graph.get("nodes", [])[:30]
                        ],
                        "relations": [
                            {
                                "type": e.get("type"),
                                "from": names.get(e.get("source"), e.get("source")),
                                "to": names.get(e.get("target"), e.get("target")),
                                "decision": e.get("decision", "unknown"),
                                "blockedBy": e.get("publicationBlockedBy", []),
                                "evidence": [
                                    {
                                        "text": _redact(
                                            str(proof.get("text", "")), 360
                                        ),
                                        "locator": proof.get("locator"),
                                    }
                                    for proof in e.get("evidence", [])[:2]
                                ],
                            }
                            for e in graph.get("edges", [])[:30]
                        ],
                    }
                )
        doc = payload.get("document", {})
        return {
            "scope": scope,
            "generation": row["generation"],
            "fingerprint": row["fingerprint"],
            "document": {
                key: doc.get(key)
                for key in (
                    "title",
                    "sourceKey",
                    "recordKey",
                    "bodyStatus",
                    "licenseStatus",
                    "publishedAt",
                    "datePrecision",
                    "version",
                    "extractionVersion",
                )
            }
            | {"sourceUrl": _source_url(doc.get("sourceUrl"))},
            "domain": domain_for_key(str(doc.get("sourceKey", ""))),
            "totalUnits": len(units),
            "offset": offset,
            "units": results,
        }


class LandscapeServer(ThreadingHTTPServer):
    """A private local server with a fixed asset set."""

    daemon_threads = True

    def __init__(self, repository: LandscapeRepository, port: int) -> None:
        self.repository = repository
        super().__init__(("127.0.0.1", port), LandscapeHandler)


class LandscapeHandler(BaseHTTPRequestHandler):
    """Serve only the dashboard and bounded read-only JSON endpoints."""

    server: LandscapeServer

    def log_message(self, format: str, *args: Any) -> None:
        LOGGER.info("data landscape request %s", args[1] if len(args) > 1 else "")

    def _send(self, status: int, body: bytes, kind: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; connect-src 'self'; style-src 'self'; script-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, value: Any) -> None:
        self._send(
            status,
            json.dumps(value, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def do_GET(self) -> None:
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        if (
            not _HOST.fullmatch(host)
            or host
            not in {
                f"127.0.0.1:{self.server.server_port}",
                f"localhost:{self.server.server_port}",
            }
            or (origin and origin not in {f"http://{host}"})
        ):
            self._json(403, {"error": "local_origin_required"})
            return
        target = urlsplit(self.path)
        if target.scheme or target.netloc or len(self.path) > 1500:
            self._json(400, {"error": "invalid_request"})
            return
        try:
            query = parse_qs(target.query, keep_blank_values=True, max_num_fields=6)
            if target.path == "/api/overview":
                result = self.server.repository.overview()
            elif target.path == "/api/sources":
                result = self.server.repository.sources(
                    query.get("domain", ["all"])[0],
                    query.get("q", [""])[0].strip(),
                    int(query.get("page", ["1"])[0]),
                )
            elif target.path == "/api/source":
                result = self.server.repository.source(
                    query.get("scope", [""])[0], int(query.get("offset", ["0"])[0])
                )
                if result is None:
                    self._json(404, {"error": "source_not_found"})
                    return
            elif target.path in {"/", "/app.js", "/style.css"}:
                name = "index.html" if target.path == "/" else target.path[1:]
                kind = (
                    "text/html"
                    if name.endswith(".html")
                    else "text/css" if name.endswith(".css") else "text/javascript"
                )
                self._send(200, (ASSETS / name).read_bytes(), kind + "; charset=utf-8")
                return
            else:
                self._json(404, {"error": "not_found"})
                return
            self._json(200, result)
        except (ValueError, IndexError, KeyError):
            self._json(400, {"error": "invalid_request"})
        except (OSError, sqlite3.Error):
            LOGGER.exception("data landscape read unavailable")
            self._json(503, {"error": "source_unavailable"})


def main() -> None:
    """Start the read-only dashboard on the loopback interface."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--mysql-snapshot", type=Path, default=DEFAULT_MYSQL)
    parser.add_argument("--port", type=int, default=18791)
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("port must be between 0 and 65535")
    logging.basicConfig(level=logging.INFO)
    server = LandscapeServer(
        LandscapeRepository(args.db, args.mysql_snapshot), args.port
    )
    LOGGER.info("Data landscape ready at http://127.0.0.1:%s", server.server_port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
