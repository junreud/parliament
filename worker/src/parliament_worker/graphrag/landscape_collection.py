"""Read aggregate collection snapshots without exposing raw records or credentials."""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

_SCRIPTS = {
    "laws": "collect_all_laws.py",
    "assembly-children": "collect_assembly_children.py",
    "government": "collect_government.py",
    "meeting-originals": "collect_meetings.py",
    "bill-attachments": "collect_bill_attachments.py",
}
_LABELS = {
    "laws": "법령 본문·별표",
    "assembly-children": "국회 의안별 공개 자료",
    "government": "정부 발표·일정",
    "meeting-originals": "회의 의사일정·회의록",
    "bill-attachments": "법안 HWP·PDF·공포안",
}
_GOVERNMENT = {
    "opm",
    "korea",
    "president-speeches",
    "president-briefings",
    "president-schedule",
}
_COMMITTEES = ("BILLJUDGECONF", "BILLLWJUDGECONF", "VCONFBILLCONFLIST")
Probe = Callable[[int | None, str], str]


def _read(root: Path, relative: Any) -> dict[str, Any] | None:
    """Read bounded snapshots only beneath the explicit private collection root."""
    if not isinstance(relative, str) or Path(relative).is_absolute():
        return None
    try:
        path = (root / relative).resolve(strict=True)
        if not path.is_relative_to(root.resolve()) or path.stat().st_size > 2_000_000:
            return None
        value = json.loads(path.read_bytes())
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, RuntimeError):
        return None


def _count(value: Any) -> int:
    """Refuse corrupt counts instead of converting missing data to zero."""
    if type(value) is not int or not 0 <= value <= 10**12:
        raise ValueError("invalid_collection_count")
    return value


def _states(value: Any) -> dict[str, int]:
    """Validate sparse state counters without silently dropping unknown states."""
    if not isinstance(value, dict):
        raise ValueError("invalid_collection_states")
    allowed = {"complete", "empty", "pending", "running", "failed", "archived"}
    if set(value) - allowed:
        raise ValueError("unknown_collection_state")
    return {key: _count(count) for key, count in value.items()}


def _metric(
    label: str, completed: int, expected: int | None, unit: str
) -> dict[str, Any]:
    """Keep a known count separate from an unconfirmed final denominator."""
    _count(completed)
    if expected is not None and _count(expected) < completed:
        raise ValueError("collection_count_exceeds_scope")
    return {"label": label, "completed": completed, "expected": expected, "unit": unit}


def _stamp(value: Any) -> str | None:
    """Expose only timezone-aware observation timestamps."""
    try:
        if not isinstance(value, str) or len(value) > 50:
            return None
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.isoformat() if parsed.tzinfo else None
    except ValueError:
        return None


def _process(pid: int | None, script: str) -> str:
    """Confirm an actual matching Python command; stale PID files are insufficient."""
    if type(pid) is not int or not 2 <= pid <= 2_147_483_647:
        return "unknown"
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "args="],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if result.returncode == 1 and not result.stdout.strip():
        return "stopped"
    if result.returncode != 0:
        return "unknown"
    pattern = (
        r"(?:^|/|\s)python[0-9.]*\s+.*\.local/full-coverage/[0-9]{8}/"
        + re.escape(script)
        + r"(?:\s|$)"
    )
    return "running" if re.search(pattern, result.stdout) else "stopped"


def _base(kind: str, data: dict[str, Any], activity: str) -> dict[str, Any]:
    """Build a whitelisted operator card with no approval implied."""
    return {
        "id": kind,
        "label": _LABELS[kind],
        "activity": activity,
        "observedAt": _stamp(data.get("observedAt")),
        "availability": "available",
        "metrics": [],
        "failureCount": 0,
        "sourceDefectRows": 0,
        "collectionVerified": False,
        "identityApproved": False,
    }


def _laws(data: dict[str, Any], activity: str) -> list[dict[str, Any]]:
    """Compare law body and discovered annex counts independently."""
    card = _base("laws", data, activity)
    expected, bodies = _count(data["expectedLaws"]), _count(data["collectedLaws"])
    refs, archived = _count(data["attachmentReferences"]), _count(
        data["archivedAttachmentReferences"]
    )
    errors = _count(data["errorCount"])
    if not expected:
        raise ValueError("empty_law_catalog")
    card.update(
        domainIds=["laws"],
        failureCount=errors,
        metrics=[
            _metric("본문 보관", bodies, expected, "건"),
            _metric("확인된 첨부 참조 보관", archived, refs, "개"),
        ],
        collectionVerified=data.get("complete") is True
        and data.get("catalogVerifiedUnchanged") is True
        and data.get("catalogMetadataVerifiedUnchanged") is True
        and data.get("originalHashesVerified") is True
        and bodies == expected
        and refs == archived
        and not errors,
        note="첨부 참조 수는 본문에서 발견된 범위입니다. 전체 법령·첨부와 최종 목록 대조를 모두 확인합니다.",
    )
    return [card]


def _partitions(
    data: dict[str, Any], activity: str, sources: tuple[str, ...], *, votes: bool
) -> dict[str, Any]:
    """Count explicit empty responses as queries, never as vote or meeting rows."""
    card = _base("assembly-children", data, activity)
    card.update(
        id="votes" if votes else "committee-records",
        label="의안별 공개 표결" if votes else "의안별 심사·회의 연결",
        domainIds=["votes"] if votes else ["meetings"],
    )
    expected = finished = empty = records = failed = 0
    for source in sources:
        value = data["bySource"][source]
        states = _states(value["states"])
        total = _count(value["parentPartitionsExpected"])
        if sum(states.values()) != total or not total:
            raise ValueError("partition_scope_mismatch")
        expected += total
        finished += states.get("complete", 0) + states.get("empty", 0)
        empty += states.get("empty", 0)
        failed += states.get("failed", 0)
        records += _count(value["storedRows"])
    card.update(
        metrics=[
            _metric("의안별 조회 확인", finished, expected, "회"),
            _metric("보관된 응답 행", records, None, "행"),
        ],
        failureCount=failed,
        collectionVerified=finished == expected and not failed,
        note=f"공식 자료 없음 응답 {empty:,}회도 조회 확인에 포함합니다. 응답 행의 신원·역할 연결은 별도 검수합니다.",
    )
    return card


def _government(data: dict[str, Any], activity: str) -> list[dict[str, Any]]:
    """Withhold the final denominator until all five source windows are closed."""
    card = _base("government", data, activity)
    sources = data["sources"]
    if (
        not isinstance(sources, dict)
        or set(sources) - _GOVERNMENT
        or any(not isinstance(value, dict) for value in sources.values())
    ):
        raise ValueError("invalid_government_sources")
    enumerated = set(sources) == _GOVERNMENT and all(
        value.get("windowEnumerated") is True for value in sources.values()
    )
    have = known = errors = 0
    for value in sources.values():
        states = _states(value["items"])
        have += states.get("archived", 0)
        known += sum(states.values())
        errors += states.get("failed", 0)
    files = _states(data["files"])
    errors += files.get("failed", 0)
    bodies_closed = enumerated and known == have
    card.update(
        domainIds=["government"],
        failureCount=errors,
        metrics=[
            _metric("발표·일정 원문 보관", have, known if enumerated else None, "건"),
            _metric(
                "첨부 파일 보관",
                files.get("archived", 0),
                sum(files.values()) if bodies_closed else None,
                "개",
            ),
        ],
        collectionVerified=bodies_closed
        and data.get("originalWindowArchived") is True
        and data.get("catalogReconciliationComplete") is True
        and not errors,
        note="기존 공식 출처 5개의 최근 90일 범위입니다. 첨부 전체 수는 모든 본문을 확인한 뒤 확정합니다.",
    )
    return [card]


def _meetings(data: dict[str, Any], activity: str) -> list[dict[str, Any]]:
    """Separate growing conference discovery, agenda rows and actual files."""
    card = _base("meeting-originals", data, activity)
    conferences, files = _states(data["conferences"]), _states(data["originalFiles"])
    closed = data.get("allParentPartitionsComplete") is True
    missing = _count(data["conferencesWithoutDownloadUrl"])
    errors = conferences.get("failed", 0) + files.get("failed", 0) + missing
    card.update(
        domainIds=["meetings"],
        failureCount=errors,
        metrics=[
            _metric(
                "의사일정 확인 회의",
                conferences.get("complete", 0),
                sum(conferences.values()) if closed else None,
                "개",
            ),
            _metric(
                "회의록 파일 보관",
                files.get("archived", 0),
                sum(files.values()) if closed else None,
                "개",
            ),
            _metric("보관된 의사일정 행", _count(data["agendaRows"]), None, "행"),
        ],
        sourceDefectRows=_count(data.get("sourceDuplicateRows", 0))
        + _count(data.get("invalidBillIdentityRows", 0)),
        collectionVerified=closed
        and data.get("complete") is True
        and not errors
        and conferences.get("complete", 0) == sum(conferences.values())
        and files.get("archived", 0) == sum(files.values()),
        note="전체 회의 대상은 의안별 조회가 끝나야 확정됩니다. 원천 중복·잘못된 식별자는 그대로 보관하고 연결을 보류합니다.",
    )
    return [card]


def _bill_attachments(data: dict[str, Any], activity: str) -> list[dict[str, Any]]:
    """Keep known input attachments distinct from full national bill coverage."""
    card = _base("bill-attachments", data, activity)
    known, scanned = _count(data["knownSources"]), _count(data["scannedSources"])
    sources, files = _states(data["sourceStates"]), _states(data["currentFiles"])
    references, archived = _count(data["knownFileReferences"]), _count(
        data["archivedFileReferences"]
    )
    if sum(sources.values()) != known or scanned != sources.get(
        "complete", 0
    ) + sources.get("empty", 0):
        raise ValueError("bill_source_count_mismatch")
    card.update(
        domainIds=["bills"],
        failureCount=sources.get("failed", 0) + files.get("failed", 0),
        sourceDefectRows=_count(data.get("unresolvedDeclaredReferences", 0)),
        metrics=[
            _metric("파일 선언 확인 의안", scanned, known, "건"),
            _metric(
                "원본 파일 보관",
                files.get("archived", 0),
                sum(files.values()) if known == scanned else None,
                "개",
            ),
            _metric("확인된 파일 참조 보관", archived, references, "개"),
        ],
        collectionVerified=False,
        note="현재 GraphRAG 입력에 알려진 의안의 첨부 범위입니다. 전체 법안 목록 수집·최종 원문 대조와 구분합니다.",
    )
    return [card]


def collection_summary(
    root: Path, *, process_probe: Probe = _process
) -> dict[str, Any] | None:
    """Return only current aggregate counts, independent of the graph DB cache.

    Args:
        root: Workspace containing an explicit active collection registry.
        process_probe: Actual-process verifier, injectable for isolated tests.

    Returns:
        Whitelisted count cards, or unknown when no registry can be read. No raw
        record, request key, remote ID, candidate relation or process ID is exposed.
    """
    directory = root / ".local/full-coverage"
    registry = _read(directory, "active-collections.json")
    if not registry or registry.get("schema") != "parliament-active-collections-v1":
        return None
    entries = registry.get("collectors")
    if not isinstance(entries, list) or len(entries) > 8:
        return None
    cards = []
    kinds = set()
    for entry in entries:
        kind = entry.get("kind") if isinstance(entry, dict) else None
        if not isinstance(kind, str) or kind not in _SCRIPTS or kind in kinds:
            continue
        kinds.add(kind)
        data = _read(directory, entry.get("progress"))
        runtime = _read(directory, entry.get("runtime")) or {}
        try:
            if data is None:
                raise ValueError("snapshot_unavailable")
            if (
                data.get("jobId")
                and runtime.get("jobId")
                and data["jobId"] != runtime["jobId"]
            ):
                raise ValueError("snapshot_job_mismatch")
            activity = process_probe(runtime.get("pid"), _SCRIPTS[kind])
            if activity not in {"running", "stopped", "unknown"}:
                activity = "unknown"
            if kind == "assembly-children":
                for sources, votes in [
                    (("nojepdqqaweusdfbi",), True),
                    (_COMMITTEES, False),
                ]:
                    try:
                        cards.append(_partitions(data, activity, sources, votes=votes))
                    except (ValueError, KeyError, TypeError):
                        missing = _base(kind, data, activity)
                        missing.update(
                            id="votes" if votes else "committee-records",
                            label=(
                                "의안별 공개 표결" if votes else "의안별 심사·회의 연결"
                            ),
                            availability="unavailable",
                        )
                        cards.append(missing)
            else:
                cards.extend(
                    {
                        "laws": _laws,
                        "government": _government,
                        "meeting-originals": _meetings,
                        "bill-attachments": _bill_attachments,
                    }[kind](data, activity)
                )
        except (ValueError, KeyError, TypeError):
            missing = _base(kind, {}, "unknown")
            missing["availability"] = "unavailable"
            cards.append(missing)
    return {
        "schema": "parliament-collection-landscape-v1",
        "pipelines": cards,
        "wholeCoverageComplete": False,
        "publicationApproved": False,
    }
