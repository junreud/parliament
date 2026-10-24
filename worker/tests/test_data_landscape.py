"""Regression checks for private, read-only data inspection."""

import json
import sqlite3
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from parliament_worker.graphrag import landscape
from parliament_worker.graphrag.landscape import LandscapeRepository, LandscapeServer
from parliament_worker.graphrag.landscape_radar import radar_summary
from parliament_worker.graphrag.store_schema import SCHEMA


@pytest.fixture(autouse=True)
def isolated_operator_snapshots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep every server test independent of real collector and radar snapshots."""
    monkeypatch.setattr(landscape, "ROOT", tmp_path)


def _state(path: Path) -> None:
    """Build a small state with one missing and one unrelated current graph."""
    payload = {
        "document": {
            "title": "법안 표본",
            "sourceKey": "lawmaking-bill-detail",
            "bodyStatus": "available",
            "licenseStatus": "unknown",
            "sourceUrl": "https://example.org/bill",
        },
        "units": [
            {"id": "u1", "text": "연락처 010-1234-5678", "locator": "문단 1"},
            {"id": "u2", "text": "두 번째 문단", "locator": "문단 2"},
        ],
    }
    graph = {
        "nodes": [
            {"id": "bill-1", "name": "법안 표본", "kind": "bill"},
            {"id": "person-1", "name": "발의자", "kind": "person"},
        ],
        "edges": [
            {
                "id": "e1",
                "source": "person-1",
                "target": "bill-1",
                "type": "lead_sponsor",
                "decision": "pending",
                "evidence": [{"text": "010-1234-5678", "locator": "문단 1"}],
            }
        ],
    }
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
        db.execute(
            "INSERT INTO sources VALUES (?,?,?,?,?)",
            ("lawmaking-bill-detail:123", "fingerprint", 1, json.dumps(payload), 1),
        )
        for key in ("lawmaking-bill-detail:123:u1", "stale:u9"):
            db.execute(
                "INSERT INTO artifacts(kind,artifact_key,version,dependency,payload,current) "
                "VALUES ('graph',?,'v1','{}',?,1)",
                (key, json.dumps(graph)),
            )


def test_overview_matches_current_source_units(tmp_path: Path) -> None:
    """A stale graph cannot inflate the collection domain coverage."""
    path = tmp_path / "graph.sqlite3"
    _state(path)
    data = LandscapeRepository(path).overview()
    assert data["totals"]["sources"] == 1
    assert data["totals"]["sourceUnits"] == 2
    assert data["totals"]["indexedSourceUnits"] == 1
    assert data["totals"]["missingSourceGraphs"] == 1
    assert data["totals"]["derivedGraphs"] == 1
    assert next(d for d in data["domains"] if d["id"] == "bills")["graphs"] == 1
    assert data["edgeDecisions"] == {"pending": 1}


def test_source_detail_redacts_contact_and_does_not_write(tmp_path: Path) -> None:
    """The detail view shows evidence while leaving private state untouched."""
    path = tmp_path / "graph.sqlite3"
    _state(path)
    before = path.read_bytes()
    repository = LandscapeRepository(path)
    detail = repository.source("lawmaking-bill-detail:123", 0)
    assert detail is not None
    assert detail["totalUnits"] == 2
    assert detail["units"][0]["indexed"] is True
    assert "010-1234-5678" not in json.dumps(detail, ensure_ascii=False)
    assert "[연락처 생략]" in detail["units"][0]["text"]
    assert path.read_bytes() == before


def test_http_refuses_nonlocal_host(tmp_path: Path) -> None:
    """A foreign Host header cannot read local candidate data."""
    path = tmp_path / "graph.sqlite3"
    _state(path)
    server = LandscapeServer(LandscapeRepository(path), 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/api/overview"
        request = Request(url, headers={"Host": "example.com"})
        try:
            urlopen(request, timeout=3)
        except HTTPError as error:
            assert error.code == 403
        else:
            raise AssertionError("foreign host was allowed")
        with urlopen(url, timeout=3) as response:
            assert json.load(response)["totals"]["sources"] == 1
    finally:
        server.shutdown()
        server.server_close()


def test_radar_is_labeled_as_a_news_shortlist(tmp_path: Path) -> None:
    """News candidates stay distinct from the official record graph."""
    folder = tmp_path / ".local/radar"
    folder.mkdir(parents=True)
    with sqlite3.connect(folder / "state.sqlite3") as db:
        db.executescript(
            "CREATE TABLE articles(id TEXT PRIMARY KEY);"
            "CREATE TABLE observations(at TEXT PRIMARY KEY);"
            "INSERT INTO articles VALUES ('a1');"
            "INSERT INTO observations VALUES ('2026-10-22');"
        )
    (folder / "public.json").write_text(
        json.dumps(
            {
                "generatedAt": "2026-10-22T00:00:00Z",
                "status": "ok",
                "items": [
                    {
                        "id": "candidate-1",
                        "title": "검토 전 후보",
                        "reviewStatus": "unreviewed",
                        "articleCount": 1,
                        "publisherCount": 1,
                        "articles": [
                            {
                                "title": "기사",
                                "url": "https://example.org/news?serviceKey=private",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    data = radar_summary(tmp_path)
    assert data is not None
    assert data["classification"] == "news_shortlist_not_official_evidence"
    assert data["articleRecords"] == 1
    assert data["candidates"][0]["reviewStatus"] == "unreviewed"
    assert data["candidates"][0]["articles"][0]["url"] is None


def test_collection_counts_refresh_independently_of_graph_cache(tmp_path, monkeypatch):
    """A collector update is visible even when the graph DB revision stays fixed."""
    from parliament_worker.graphrag import landscape

    monkeypatch.setattr(landscape, "ROOT", tmp_path)
    path = tmp_path / "graph.sqlite3"
    _state(path)
    folder = tmp_path / ".local/full-coverage"
    folder.mkdir(parents=True)
    (folder / "active-collections.json").write_text(
        json.dumps(
            {
                "schema": "parliament-active-collections-v1",
                "collectors": [
                    {
                        "kind": "laws",
                        "progress": "progress.json",
                        "runtime": "runtime.json",
                    }
                ],
            }
        )
    )
    (folder / "runtime.json").write_text(json.dumps({"pid": 0, "state": "running"}))
    progress = {
        "observedAt": "2026-10-22T00:00:00Z",
        "expectedLaws": 10,
        "collectedLaws": 1,
        "attachmentReferences": 0,
        "archivedAttachmentReferences": 0,
        "errorCount": 0,
    }
    (folder / "progress.json").write_text(json.dumps(progress))
    repository = LandscapeRepository(path)
    first = repository.overview()
    assert first["collection"]["pipelines"][0]["metrics"][0]["completed"] == 1
    progress["collectedLaws"] = 2
    (folder / "progress.json").write_text(json.dumps(progress))
    second = repository.overview()
    assert second["totals"] == first["totals"]
    assert second["collection"]["pipelines"][0]["metrics"][0]["completed"] == 2
    assert second["collection"]["pipelines"][0]["activity"] == "unknown"
