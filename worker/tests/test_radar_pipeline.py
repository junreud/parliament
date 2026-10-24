"""Failure visibility, raw evidence and atomic public projections."""

import json
from datetime import timedelta
from pathlib import Path

from test_radar import NOW

from parliament_worker.radar.feeds import SOURCES, TRENDS_URL
from parliament_worker.radar.pipeline import collect_once

RSS = b"""<rss><channel><item><title>National Assembly budget hearing</title>
<link>https://www.yna.co.kr/view/20261017</link><pubDate>Sat, 17 Oct 2026 07:00:00 GMT</pubDate>
</item></channel></rss>"""


def test_partial_failure_exports_only_successful_metadata_and_records_raw(
    tmp_path: Path,
):
    def fetch(url: str) -> bytes:
        if url == SOURCES[0].url:
            return RSS
        raise TimeoutError("private internal text must not leak")

    result = collect_once(tmp_path / "state", tmp_path / "feed.json", NOW, fetch)
    assert result["status"] == "partial"
    assert len(result["items"]) == 1
    assert result["shortfall"] == 9
    assert len(result["sources"]) == len(SOURCES) + 1
    assert "private internal" not in json.dumps(result)
    assert list((tmp_path / "state" / "raw").glob("*.xml"))
    assert result["selectionMethod"] == "rules-shortlist-human-review"
    assert not result["baselineAvailable"]


def test_total_failure_retains_old_timestamp_and_exposes_failure(tmp_path: Path):
    def first(url: str) -> bytes:
        return RSS if url == SOURCES[0].url else b"<rss><channel/></rss>"

    collect_once(tmp_path / "state", tmp_path / "feed.json", NOW, first)

    def failure(_: str) -> bytes:
        raise TimeoutError()

    result = collect_once(
        tmp_path / "state", tmp_path / "feed.json", NOW + timedelta(days=1), failure
    )
    assert result["status"] == "unavailable"
    assert result["generatedAt"] == "2026-10-17T08:00:00Z"
    assert result["lastAttemptAt"] == "2026-10-18T08:00:00Z"
    assert result["items"]
    assert len(list((tmp_path / "state" / "runs").glob("*/run.json"))) == 2


def test_successful_empty_feed_is_empty_not_failure_or_examples(tmp_path: Path):
    result = collect_once(
        tmp_path / "state",
        tmp_path / "feed.json",
        NOW,
        lambda _: b"<rss><channel/></rss>",
    )
    assert result["status"] == "ok"
    assert result["items"] == []
    assert result["shortfall"] == 10
