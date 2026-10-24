"""Aggregate consented, topic-free beta observations without inventing missing data."""

from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo

SEOUL = ZoneInfo("Asia/Seoul")
ALLOWED_EVENTS = {
    "enrolled",
    "explainer_opened",
    "source_opened",
    "timeline_expanded",
    "withdrawn",
}
ALLOWED_CONTEXTS = {"organic", "interview", "reminder", "unknown"}
KEYS = (
    "enrolled",
    "activated",
    "d7_eligible",
    "d7_organic_returned",
    "d7_prompted_returned",
    "d7_unknown_context_returned",
    "d7_organic_rate",
)


def timestamp(value: str) -> datetime:
    """Parse an offset-aware timestamp; reject implicit local time.

    Args:
        value: ISO 8601 timestamp with an explicit offset or Z suffix.

    Returns:
        An offset-aware datetime normalized to Seoul.
    """
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp requires an explicit timezone")
    return parsed.astimezone(SEOUL)


def aggregate_events(
    rows: Optional[Iterable[Dict[str, str]]], as_of: datetime
) -> Dict[str, Any]:
    """Calculate observed activation and mature D7 by recruitment cohort.

    Activation requires an open followed by a depth action in the same visit
    context within 30 minutes.
    D7 requires the full 168 hours after activation and a later Seoul calendar
    day open before the 168-hour endpoint. Prompted visits never become organic
    returns.
    Rows must be an explicitly consented, private research export, not page logs.
    No issue, person, party, URL, political preference or contact field is read.
    """
    cutoff = timestamp(as_of.isoformat())
    if rows is None:
        return {
            name: {key: None for key in KEYS} for name in ("all", "friend", "external")
        }
    people: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        if row["event"] not in ALLOWED_EVENTS:
            raise ValueError("unsupported event")
        if row["cohort"] not in {"friend", "external"}:
            raise ValueError("cohort must be friend or external")
        if row["visit_context"] not in ALLOWED_CONTEXTS:
            raise ValueError("unsupported visit context")
        at = timestamp(row["event_at"])
        if at < timestamp(row["consented_at"]) or at > cutoff:
            continue
        if not row["participant_id"].strip():
            raise ValueError("participant_id is required")
        people.setdefault(row["participant_id"], []).append({**row, "at": at})
    result: Dict[str, Any] = {
        name: {key: 0 for key in KEYS} for name in ("all", "friend", "external")
    }
    for observations in people.values():
        observations.sort(key=lambda value: value["at"])
        if any(value["event"] == "withdrawn" for value in observations):
            continue
        cohorts = {value["cohort"] for value in observations}
        if len(cohorts) != 1:
            raise ValueError("a participant cannot change recruitment cohort")
        totals = [result["all"], result[observations[0]["cohort"]]]
        for total in totals:
            total["enrolled"] += 1
        opened_by_context: Dict[str, datetime] = {}
        activated: Optional[datetime] = None
        for observation in observations:
            if observation["event"] == "explainer_opened":
                opened_by_context[observation["visit_context"]] = observation["at"]
            elif observation["event"] in {"source_opened", "timeline_expanded"}:
                opened = opened_by_context.get(observation["visit_context"])
                if opened and timedelta(0) <= observation["at"] - opened <= timedelta(
                    minutes=30
                ):
                    activated = observation["at"]
                    break
        if activated is None:
            continue
        for total in totals:
            total["activated"] += 1
        until = activated + timedelta(days=7)
        if cutoff < until:
            continue
        returns = [
            value
            for value in observations
            if value["event"] == "explainer_opened"
            and activated < value["at"] < until
            and value["at"].date() > activated.date()
        ]
        for total in totals:
            total["d7_eligible"] += 1
            total["d7_organic_returned"] += int(
                any(value["visit_context"] == "organic" for value in returns)
            )
            total["d7_prompted_returned"] += int(
                any(
                    value["visit_context"] in {"interview", "reminder"}
                    for value in returns
                )
            )
            total["d7_unknown_context_returned"] += int(
                any(value["visit_context"] == "unknown" for value in returns)
            )
    for total in result.values():
        eligible = total["d7_eligible"]
        total["d7_organic_rate"] = (
            total["d7_organic_returned"] / eligible if eligible else None
        )
    return result


def merge_external_report(value: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Preserve a backend aggregate as attributed data without filling gaps.

    The backend remains the source of truth for its own cohort definitions.
    This wrapper avoids silently combining different event or D7 definitions.
    """
    if value is None:
        return {"status": None, "report": None}
    if not isinstance(value, dict):
        raise ValueError("backend report must be a JSON object")
    return {"status": "supplied_unmerged", "report": value}


def normalize_backend_report(value: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Map the authenticated beta report contract while preserving unknowns.

    This is a display adapter, not a recalculation. Backend cohort results stay
    separate from private-export totals and retain their own observedAt value.
    """
    field_map = {
        "enrolled": "enrolled",
        "activated": "activated",
        "d7_eligible": "d7Eligible",
        "d7_returned": "d7Returned",
        "d7_organic_returned": "organicReturned",
        "d7_prompted_returned": "researchReturned",
        "d7_total_rate": "d7Retention",
    }
    result: Dict[str, Any] = {
        "observed_at": value.get("observedAt") if value else None,
        "calendar_zone": value.get("calendarZone") if value else None,
        "retention_days": value.get("retentionDays") if value else None,
        "cohorts": {
            name: {key: None for key in (*field_map, "d7_organic_rate")}
            for name in ("all", "friend", "external")
        },
        "acquisition": value.get("acquisition") if value else None,
    }
    if value is None:
        return result
    for cohort in value.get("cohorts", []):
        name = cohort.get("cohort")
        if name not in result["cohorts"]:
            raise ValueError("unsupported backend cohort")
        normalized = {key: cohort.get(source) for key, source in field_map.items()}
        eligible = normalized["d7_eligible"]
        organic = normalized["d7_organic_returned"]
        normalized["d7_organic_rate"] = (
            organic / eligible if eligible and organic is not None else None
        )
        if not eligible:
            normalized["d7_total_rate"] = None
        result["cohorts"][name] = normalized
    return result
