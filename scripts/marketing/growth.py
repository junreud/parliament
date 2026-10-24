"""Evidence-only release preflight and first 24/72-hour Instagram observations."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from marketing.board import release_errors
from marketing.metrics import timestamp
from marketing.urls import public_https


def publication_preflight(row: Dict[str, str], as_of: datetime) -> List[str]:
    """Hold elapsed slots, stale sources and previously reserved publications.

    A clean result permits platform work, but does not prove an upload or post.
    All required source/approval references must also pass board validation.
    """
    now = timestamp(as_of.isoformat())
    errors = release_errors(row)
    if timestamp(row["scheduled_at"]) <= now:
        errors.append("slot elapsed; select a future unoccupied day")
    if row.get("scheduler_id") or row.get("published_url"):
        errors.append("already reserved/published; reconcile platform before creating")
    try:
        age = (now - timestamp(row.get("source_checked_at", ""))).total_seconds()
        if not 0 <= age <= 24 * 3600:
            errors.append("source freshness requires a new check within 24 hours")
    except (ValueError, TypeError):
        errors.append("source freshness evidence missing")
    if row.get("review_status") != "approved" or not row.get("approval_evidence"):
        errors.append("explicit human approval missing")
    if not row.get("source_evidence") or not row.get("primary_source_urls"):
        errors.append("immutable original-source evidence missing")
    return errors


def observation(
    row: Dict[str, str], raw: Dict[str, Any], as_of: datetime, window: int
) -> Optional[Dict[str, Any]]:
    """Normalize one matching, mature, cumulative per-post observation.

    Args:
        row: Board entry with actual publication URL/time, not a planning date.
        raw: Explicitly mapped provider fields, including the exact post URL.
        as_of: Real observation time.
        window: First observation after 24 or 72 hours.

    Returns:
        A measurement or None when absent, immature, mismatched or already read.
    """
    if window not in {24, 72}:
        raise ValueError("observation window must be 24 or 72")
    if (
        not public_https(row.get("published_url", ""))
        or not row.get("published_at")
        or raw.get("url") != row["published_url"]
        or row.get(f"observation_{window}h_evidence")
    ):
        return None
    hours = (
        timestamp(as_of.isoformat()) - timestamp(row["published_at"])
    ).total_seconds() / 3600
    if hours < window:
        return None
    result = {
        "asset_id": row["asset_id"],
        "published_url": row["published_url"],
        "observed_at": as_of.isoformat(),
        "window_hours": window,
        "elapsed_hours": hours,
        "scope": "individual_post",
        "aggregation": "cumulative_at_observation",
        "profile_visits": None,
        "link_clicks": None,
    }
    for field in (
        "reach",
        "saves",
        "shares",
        "views",
        "nonfollower_reach",
        "average_watch_seconds",
    ):
        value = raw.get(field)
        if value is not None and (not isinstance(value, (int, float)) or value < 0):
            raise ValueError(f"invalid non-negative metric: {field}")
        result[field] = value
    for field in ("saves", "shares"):
        result[f"{field}_per_100_reached"] = (
            result[field] / result["reach"] * 100
            if result["reach"] and result[field] is not None
            else None
        )
    return result


def save_observation(value: Dict[str, Any], state: Path) -> Path:
    """Persist one canonical asset/window record with exclusive file creation."""
    asset = value["asset_id"]
    window = value["window_hours"]
    if not asset.isalnum() or window not in {24, 72}:
        raise ValueError("invalid observation identity")
    state.mkdir(parents=True, exist_ok=True)
    path = state / f"{asset}-{window}h.json"
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return path
