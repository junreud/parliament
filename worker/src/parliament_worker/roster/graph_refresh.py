"""Stage only changed official roster candidates for the private GraphRAG input."""

import hashlib
import json
from pathlib import Path
from typing import Any

from parliament_worker.graphrag.inputs import read_sources, sources_from_batch
from parliament_worker.graphrag.source_observations import normalize_observed_at
from parliament_worker.knowledge.files import private_write
from parliament_worker.roster.batches import candidate_batches

MATERIAL_FIELDS = (
    "name",
    "nameSurface",
    "position",
    "organizationNamespace",
    "organizationCode",
    "organizationName",
    "party",
    "districtLabel",
    "termLabel",
    "committeeLabel",
    "currentness",
    "sourceUrl",
    "evidenceLocator",
    "excerpt",
    "sourcePublishedAt",
    "datePrecision",
    "qualificationObservedAt",
    "licenseStatus",
    "format",
)


def _key(record: dict[str, Any]) -> str:
    """Use a source-scoped external identifier, never a person's name."""
    return record["namespace"] + ":" + record["sourceRecordId"]


def _index(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Reject duplicate or malformed identities before computing differences."""
    indexed = {}
    for record in records:
        key = _key(record)
        if key in indexed:
            raise ValueError("duplicate roster source identity")
        indexed[key] = record
    return indexed


def _material_value(record: dict[str, Any], field: str) -> Any:
    """Treat the old and current HTML locator prefixes as the same selector."""
    value = record.get(field)
    if field == "evidenceLocator" and isinstance(value, str):
        if value.startswith("HTML "):
            return "html:" + value[5:]
    return value


def validate_run_pair(
    previous: list[dict[str, Any]],
    previous_coverage: list[dict[str, Any]],
    current: list[dict[str, Any]],
    current_coverage: list[dict[str, Any]],
) -> None:
    """Require equivalent complete source sets before comparing observations."""
    for coverage, records in (
        (previous_coverage, previous),
        (current_coverage, current),
    ):
        if not isinstance(coverage, list) or not coverage:
            raise ValueError("missing roster source set")
        if not all(item.get("complete") is True for item in coverage):
            raise ValueError("incomplete roster observation")
        if sum(item.get("recordCount", -1) for item in coverage) != len(records):
            raise ValueError("roster coverage count mismatch")
    old_specs = [item["sourceSpec"] for item in previous_coverage]
    new_specs = [item["sourceSpec"] for item in current_coverage]
    if old_specs != new_specs:
        raise ValueError("roster source set changed; establish a new baseline")


def plan_refresh(
    previous: list[dict[str, Any]],
    current: list[dict[str, Any]],
    *,
    complete: bool,
) -> dict[str, Any]:
    """Classify a complete roster snapshot without retiring absent people.

    Args:
        previous: Last complete observation of the same selected source set.
        current: Newly collected records with fixed source positions and hashes.
        complete: Whether every selected source passed its coverage checks.

    Returns:
        New and materially changed candidates plus explicit review queues.
    """
    if not complete:
        raise ValueError("incomplete roster observation cannot update graph")
    old, new = _index(previous), _index(current)
    staged: list[dict[str, Any]] = []
    identity_review: list[str] = []
    unchanged = 0
    for key, record in sorted(new.items()):
        before = old.get(key)
        if before is None:
            staged.append(record)
        elif before["name"] != record["name"]:
            identity_review.append(key)
        elif any(
            _material_value(before, field) != _material_value(record, field)
            for field in MATERIAL_FIELDS
        ):
            staged.append(record)
        else:
            unchanged += 1
    return {
        "stage": staged,
        "unchanged": unchanged,
        "identityReview": identity_review,
        "removedForReview": sorted(old.keys() - new.keys()),
        "previousCount": len(previous),
        "currentCount": len(current),
    }


def _profile_record_id(spec: dict[str, Any]) -> str:
    """Match the source-local record identity used by the profile collector."""
    return (
        spec.get("sourceRecordId")
        or "provisional-profile:"
        + hashlib.sha256(
            (
                spec["sourceUrl"]
                + "\0"
                + spec["position"]
                + "\0"
                + spec["expectedName"]
            ).encode()
        ).hexdigest()
    )


def _successful_profiles(
    result: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Associate each complete profile with its exact source-local record."""
    specs = {spec["id"]: spec for spec in result["sourceSpecs"]}
    observations = {item["id"]: item for item in result["observations"]}
    if (
        len(specs) != len(result["sourceSpecs"])
        or len(observations) != len(result["observations"])
        or set(specs) != set(observations)
    ):
        raise ValueError("profile source observation mismatch")
    records = _index(result["records"])
    success = {}
    for identifier, spec in specs.items():
        if observations[identifier]["status"] != "success":
            continue
        key = "KR_OFFICE_PROFILE_CANDIDATE:" + _profile_record_id(spec)
        row = records.pop(key, None)
        if row is None:
            raise ValueError("successful profile lacks its fixed record")
        success[identifier] = row
    if records:
        raise ValueError("profile record lacks successful source observation")
    return specs, success


def plan_profile_refresh(
    previous: dict[str, Any], current: dict[str, Any]
) -> dict[str, Any]:
    """Compare independent profile successes without retiring failed sources.

    Args:
        previous: Immutable prior profile collection receipt.
        current: Immutable newer profile collection receipt.

    Returns:
        Private changed candidates and separate source/identity review queues.
    """
    _, old_success = _successful_profiles(previous)
    new_specs, new_success = _successful_profiles(current)
    current_keys = {_key(record) for record in new_success.values()}
    comparable_old = [
        record for record in old_success.values() if _key(record) in current_keys
    ]
    plan = plan_refresh(comparable_old, list(new_success.values()), complete=True)
    plan["sourceFailures"] = sorted(set(new_specs) - set(new_success))
    listed_source_keys = {
        "KR_OFFICE_PROFILE_CANDIDATE:" + _profile_record_id(spec)
        for spec in new_specs.values()
    }
    plan["removedForReview"] = sorted(
        _key(record)
        for record in old_success.values()
        if _key(record) not in listed_source_keys
    )
    return plan


def backfill_ungrounded_profiles(
    plan: dict[str, Any],
    current: dict[str, Any],
    graph_sources: list[dict[str, Any]],
) -> dict[str, Any]:
    """Add successful official profiles whose source-local graph has no text.

    A prior successful collection can predate GraphRAG staging. Comparing only
    consecutive collections would call it unchanged forever, even though the
    graph still holds a zero-unit provisional candidate. Match by exact source
    record ID and hold any changed identity for review.

    Args:
        plan: Independent prior/current profile comparison.
        current: Complete current profile collection receipt.
        graph_sources: Active private GraphRAG source revisions.

    Returns:
        A new plan with source-grounded backfill candidates and review holds.
    """
    _, successful = _successful_profiles(current)
    existing = {source["scope"]: source for source in graph_sources}
    staged = {_key(record): record for record in plan["stage"]}
    identity_review = set(plan["identityReview"])
    unavailable = set()
    added = 0
    for record in successful.values():
        key = _key(record)
        if key in staged or key in identity_review:
            continue
        source = existing.get("roster_" + key)
        if source is not None and source["payload"]["units"]:
            continue
        if source is not None:
            people = [
                entity["name"]
                for entity in source["payload"]["entities"]
                if entity["kind"] == "person"
            ]
            if len(people) != 1 or people[0] != record["name"]:
                identity_review.add(key)
                continue
        projected = sources_from_batch(candidate_batches([record])[0])
        if len(projected) != 1 or not projected[0]["payload"]["units"]:
            unavailable.add(key)
            continue
        staged[key] = record
        added += 1
    return {
        **plan,
        "stage": [staged[key] for key in sorted(staged)],
        "identityReview": sorted(identity_review),
        "unavailableForGraph": sorted(unavailable),
        "unchanged": max(0, plan["unchanged"] - added),
        "backfilledCount": added,
    }


def _existing_identity_map(sources: list[dict[str, Any]]) -> dict[str, str]:
    """Carry forward IDs already used by private source-local graph snapshots."""
    mapping: dict[str, str] = {}
    for source in sources:
        for entity in source["payload"].get("entities", []):
            if entity["kind"] != "person":
                continue
            for identifier in entity["identifiers"]:
                key = identifier["namespace"] + ":" + identifier["value"]
                prior = mapping.setdefault(key, entity["id"])
                if prior != entity["id"]:
                    raise ValueError("conflicting graph person identity")
    return mapping


def stage_refresh(
    plan: dict[str, Any],
    graph_input: Path,
    identity_map: dict[str, str] | None = None,
) -> list[Path]:
    """Append immutable pending batches to an existing complete input boundary.

    Args:
        plan: Result of :func:`plan_refresh` from complete sources.
        graph_input: Directory already watched by the private GraphRAG worker.
        identity_map: Additional operator-verified external ID to public ID map.

    Returns:
        Paths to staged immutable candidate batches.
    """
    if graph_input.is_symlink() or not graph_input.is_dir():
        raise ValueError("graph input must be an existing safe directory")
    files = sorted(graph_input.glob("*.json"))
    existing = read_sources([graph_input]) if files else []
    mapping = _existing_identity_map(existing)
    for key, value in (identity_map or {}).items():
        if key in mapping and mapping[key] != value:
            raise ValueError("verified identity conflicts with existing graph")
        mapping[key] = value
    batches = candidate_batches(plan["stage"], mapping)
    latest = {source["scope"]: source for source in existing}
    for batch in batches:
        for source in sources_from_batch(batch):
            prior = latest.get(source["scope"])
            if prior and source["fingerprint"] != prior["fingerprint"]:
                observed_at = normalize_observed_at(source["observedAt"])
                prior_observed_at = normalize_observed_at(prior["observedAt"])
                if (
                    observed_at is None
                    or prior_observed_at is None
                    or observed_at <= prior_observed_at
                ):
                    raise ValueError("stale or conflicting graph observation")
            latest[source["scope"]] = source
    staged = []
    for batch in batches:
        path = graph_input / (batch["id"] + ".json")
        private_write(
            path,
            json.dumps(batch, ensure_ascii=False, sort_keys=True, indent=2).encode(),
        )
        staged.append(path)
    return staged
