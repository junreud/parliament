"""Validate configurable feed plans without turning plans into publications."""

from collections import Counter
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from marketing.metrics import timestamp
from marketing.urls import public_https

LEGACY = {
    "assets": {"carousel": 10, "reel": 2},
    "publication": {
        "start_date": "2026-10-19",
        "end_date": "2026-11-13",
        "weekdays": [0, 2, 4],
        "time": "19:30",
        "daily_limit": 1,
    },
}
RELEASE_STATES = {"ready", "scheduled", "published"}


def validate_board(
    rows: List[Dict[str, str]], config: Optional[Dict[str, Any]] = None
) -> List[str]:
    """Check calendar coverage, approval, CTA and separate platform evidence.

    Args:
        rows: Editorial board, including explicitly missed planning slots.
        config: Campaign-specific cadence; omitted uses the historic contract.

    Returns:
        All detected errors without mutating the board or contacting a platform.
    """
    settings = config or LEGACY
    policy = settings.get("publication", LEGACY["publication"])
    start = date.fromisoformat(policy["start_date"])
    end = date.fromisoformat(policy["end_date"])
    days = {
        start + timedelta(days=i)
        for i in range((end - start).days + 1)
        if (start + timedelta(days=i)).weekday() in policy["weekdays"]
    }
    errors: List[str] = []
    if len(rows) != len(days):
        errors.append(f"board must contain exactly {len(days)} planned assets")
    expected = {
        k: v
        for k, v in settings.get("assets", LEGACY["assets"]).items()
        if isinstance(v, int)
    }
    if Counter(row.get("format") for row in rows) != expected:
        errors.append(f"asset mix must match {expected}")
    if len({row.get("asset_id") for row in rows}) != len(rows):
        errors.append("asset IDs must be unique")
    seen: Counter = Counter()
    for row in rows:
        asset = row.get("asset_id", "unknown")
        try:
            at = timestamp(row.get("scheduled_at", ""))
        except (ValueError, TypeError):
            errors.append(f"{asset}: invalid scheduled_at")
            continue
        seen[at.date()] += 1
        if at.date() not in days or at.strftime("%H:%M:%S") != policy["time"] + ":00":
            errors.append(f"{asset}: slot outside approved campaign calendar/time")
        if seen[at.date()] > policy.get("daily_limit", 1):
            errors.append(f"{asset}: duplicate daily slot")
        if row.get("app_url") and not public_https(row["app_url"]):
            errors.append(f"{asset}: app URL is not public HTTPS")
        if row.get("status") in RELEASE_STATES:
            if row.get("review_status") != "approved":
                errors.append(f"{asset}: human review required")
            if config and "publication" in config:
                errors.extend(release_errors(row))
            elif not public_https(row.get("app_url", "")):
                errors.append(f"{asset}: review and public app URL required")
        if row.get("status") == "scheduled" and config and "publication" in config:
            if not row.get("scheduler_id") or not row.get("scheduler_receipt"):
                errors.append(f"{asset}: scheduler ID and receipt required")
        if row.get("status") == "published":
            if not public_https(row.get("published_url", "")):
                errors.append(f"{asset}: published URL evidence required")
            try:
                timestamp(row.get("published_at", ""))
            except (ValueError, TypeError):
                errors.append(f"{asset}: actual published time required")
    if set(seen) != days:
        errors.append("calendar contains missing or unexpected days")
    return errors


def release_errors(row: Dict[str, str]) -> List[str]:
    """Require immutable source and approval references for releasable material."""
    asset = row["asset_id"]
    errors: List[str] = []
    for field in ("approval_evidence", "source_evidence", "primary_source_urls"):
        if not row.get(field):
            errors.append(f"{asset}: {field} required")
    try:
        timestamp(row.get("source_checked_at", ""))
    except (ValueError, TypeError):
        errors.append(f"{asset}: source check timestamp required")
    cta = row.get("cta_type")
    if cta not in {"account_followup", "official_source", "app_issue"}:
        errors.append(f"{asset}: explicit CTA type required")
    if cta == "app_issue" and (
        not public_https(row.get("app_url", ""))
        or not row.get("app_issue_id")
        or not row.get("app_link_verified_at")
        or not row.get("app_link_evidence")
    ):
        errors.append(f"{asset}: verified exact public app issue link required")
    return errors
