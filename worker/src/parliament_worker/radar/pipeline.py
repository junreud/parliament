"""Atomic read-only feed exports and immutable collection evidence."""

import fcntl
import hashlib
import json
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from parliament_worker.radar.feeds import SOURCES, TRENDS_URL, parse_feed, parse_trends
from parliament_worker.radar.models import iso
from parliament_worker.radar.ranking import candidates
from parliament_worker.radar.store import RadarStore


def write_json(path: Path, value: dict) -> None:
    """Replace a fixed output atomically without exposing a partial response."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def brief(page: dict) -> str:
    """Produce a private candidate handoff with links and explicit review gaps."""
    lines = [
        f"# {page['date']} 정치·공공정책 이슈 후보",
        "",
        f"수집: {page['generatedAt']} / 상태: {page['status']} / 후보 {len(page['items'])}/10",
        "",
        "규칙 기반 후보입니다. 보도량은 사실의 확실성이나 여론을 뜻하지 않습니다.",
        "게시 추천 1~2건은 공식 원문과 전후 맥락을 사람이 확인한 뒤 별도 편집 보고서에 기록합니다.",
        "",
    ]
    for index, item in enumerate(page["items"], 1):
        lines.extend(
            [
                f"## {index}. {item['title']}",
                "",
                f"- 후보 ID: {item['id']}",
                f"- 선정 실마리: {item['reason']}",
                f"- 신호: 기사 {item['articleCount']} / 매체 {item['publisherCount']} / 유사 제목 제외 신호 {item['independentSignals']}",
                f"- 비교 상태: {item['growth']['status']} (초기 관측에 증가율 없음)",
                "- 편집 질문: 발언·주장인가, 실제 결정인가? 공식 원문에서 어디까지 확인되는가?",
                "- 원문 근거 검수: 대기. 기사 링크는 보도의 출처이며 공식 확인을 대신하지 않습니다.",
            ]
        )
        lines.extend(
            f"- [{a['publisher']}: {a['title']}]({a['url']}) — {a['publishedAt']}"
            for a in item["articles"]
        )
        lines.append("")
    lines.extend(["## 수집 상태", ""])
    lines.extend(
        f"- {s['name']}: {s['status']} / 유효 기사 {s.get('items', 0)} / {s.get('error', '')}"
        for s in page["sources"]
    )
    return "\n".join(lines) + "\n"


def collect_once(
    state: Path, public_output: Path, now: datetime, fetch: Callable[[str], bytes]
) -> dict:
    """Collect one bounded run, serialize concurrent runs and preserve failure state."""
    state.mkdir(parents=True, exist_ok=True)
    with (state / "collector.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("radar collector already running") from error
        return _collect(state, public_output, now, fetch)


def _collect(
    state: Path, output: Path, now: datetime, fetch: Callable[[str], bytes]
) -> dict:
    store = RadarStore(state / "state.sqlite3")
    run_id = now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    run_dir = state / "runs" / run_id
    run_dir.mkdir(parents=True)
    raw_dir = state / "raw"
    raw_dir.mkdir(exist_ok=True)
    articles, trends, health = [], [], []
    successes = 0
    try:
        for source in SOURCES:
            entry = {"name": source.publisher, "url": source.url, "kind": "news"}
            try:
                raw = fetch(source.url)
                digest = hashlib.sha256(raw).hexdigest()
                path = raw_dir / (digest + ".xml")
                if not path.exists():
                    path.write_bytes(raw)
                parsed = parse_feed(raw, source, now)
                articles.extend(parsed)
                successes += 1
                entry.update(
                    status="ok",
                    items=len(parsed),
                    rawSha256=digest,
                    note="명시된 게시 시각·최근 72시간·허용 원문 주소를 충족한 항목만 집계",
                )
            except Exception as error:
                entry.update(status="error", items=0, error=type(error).__name__)
            health.append(entry)
        entry = {"name": "Google Trends KR", "url": TRENDS_URL, "kind": "search"}
        try:
            raw = fetch(TRENDS_URL)
            digest = hashlib.sha256(raw).hexdigest()
            (raw_dir / (digest + ".xml")).write_bytes(raw)
            trends = parse_trends(raw, now)
            entry.update(status="ok", items=len(trends), rawSha256=digest)
        except Exception as error:
            entry.update(status="error", items=0, error=type(error).__name__)
        health.append(entry)
        if successes:
            store.observe(articles, now)
            baseline = store.has_baseline(now)
            items = candidates(
                store.articles(now),
                now,
                store.first_seen(),
                baseline=baseline,
                trends=trends,
            )
            page = {
                "schemaVersion": 1,
                "date": now.astimezone(ZoneInfo("Asia/Seoul")).date().isoformat(),
                "runId": run_id,
                "generatedAt": iso(now),
                "lastAttemptAt": iso(now),
                "status": (
                    "ok" if all(s["status"] == "ok" for s in health) else "partial"
                ),
                "selectionMethod": "rules-shortlist-human-review",
                "baselineAvailable": baseline,
                "sources": health,
                "items": items,
                "shortfall": max(0, 10 - len(items)),
                "notice": "언론 보도에서 발견한 이슈 후보입니다. 보도량·검색량은 사실 확인이나 국민 여론을 뜻하지 않습니다.",
            }
        else:
            try:
                page = json.loads(output.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                page = {
                    "schemaVersion": 1,
                    "date": now.astimezone(ZoneInfo("Asia/Seoul")).date().isoformat(),
                    "generatedAt": iso(now),
                    "items": [],
                    "shortfall": 10,
                    "selectionMethod": "rules-shortlist-human-review",
                    "baselineAvailable": False,
                    "notice": "뉴스 수집에 실패했습니다. 기존 자료의 시각을 확인하세요.",
                }
            page.update(
                status="unavailable",
                lastAttemptAt=iso(now),
                sources=health,
                runId=run_id,
            )
        write_json(run_dir / "run.json", page)
        (run_dir / "candidates.md").write_text(brief(page), encoding="utf-8")
        write_json(output, page)
        write_json(
            state / "latest.json",
            {
                "runId": run_id,
                "runPath": str(run_dir),
                "publicOutput": str(output),
                "status": page["status"],
            },
        )
        return page
    finally:
        store.close()
