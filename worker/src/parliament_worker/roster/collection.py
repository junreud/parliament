"""Collect complete or explicitly partial rosters with immutable private originals."""

import hashlib
import json
import re
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from parliament_worker.http import validate_official_url
from parliament_worker.knowledge.files import private_read, private_write
from parliament_worker.roster.adapters import PARSERS, page_url


def collect_roster(
    source: dict[str, Any],
    fetcher: Callable[[str], bytes],
    output: Path,
    job_id: str,
    *,
    delay: float = 0.0,
) -> dict[str, Any]:
    """Preserve successes and failures without inventing missing officeholders.

    Args:
        source: Explicit current source adapter, page limit and official URL.
        fetcher: Bounded public-source fetcher with redirect and DNS validation.
        output: Explicit private raw/observation destination.
        job_id: Stable replay identifier for this observation run.
        delay: Minimum interval between source requests in seconds.

    Returns:
        Source-local candidates and measured completeness; no public decision.
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_id):
        raise ValueError("invalid roster job")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", source.get("id", "")):
        raise ValueError("invalid roster source identity")
    adapter = source.get("adapter")
    if adapter not in PARSERS or not 1 <= source.get("maxPages", 1) <= 500:
        raise ValueError("invalid roster adapter or page bounds")
    if not 1 <= source.get("pageSize", 30) <= 200 or not 0 <= delay <= 10:
        raise ValueError("invalid roster request bounds")
    validate_official_url(source["url"])
    receipt = output / "runs" / job_id / (source["id"] + ".json")
    if receipt.exists():
        prior = json.loads(private_read(receipt, max_bytes=20_000_000))
        if prior["sourceSpec"] != source:
            raise ValueError("roster job replay source conflict")
        return prior
    records, observations, errors, exclusions = [], [], [], []
    seen, expected, accounted = set(), None, 0
    seen_local_offices: set[tuple[str, str]] = set()
    for page in range(1, source.get("maxPages", 1) + 1):
        url = page_url(source, page)
        stamp = datetime.now(timezone.utc).isoformat()
        try:
            raw = fetcher(url)
            raw_hash = hashlib.sha256(raw).hexdigest()
            private_write(output / "raw" / (raw_hash + ".bin"), raw)
            observation = {
                "url": url,
                "observedAt": stamp,
                "rawHash": raw_hash,
                "status": "success",
                "page": page,
            }
            observations.append(observation)
            parsed = (
                PARSERS[adapter](raw, current_term=source.get("currentTerm", "09"))
                if adapter == "namk"
                else PARSERS[adapter](raw)
            )
            if expected is None:
                expected = parsed.total
            elif expected != parsed.total:
                errors.append({"page": page, "reason": "total_changed"})
                break
            exclusions.extend(parsed.exclusions)
            accounted += len(parsed.records) + (
                len(parsed.exclusions) if adapter == "namk" else parsed.vacancies
            )
            for record in parsed.records:
                identity = (record["namespace"], record["sourceRecordId"])
                if identity in seen:
                    raise ValueError("duplicate_record")
                if adapter in {"namk", "gaok"}:
                    office = (
                        record["organizationNamespace"],
                        record["organizationCode"],
                    )
                    if office in seen_local_offices:
                        raise ValueError("duplicate_office")
                    seen_local_offices.add(office)
                seen.add(identity)
                records.append(
                    record
                    | {
                        "sourceUrl": url,
                        "rawHash": raw_hash,
                        "observedAt": stamp,
                        "page": page,
                    }
                )
            if adapter == "namk":
                for exclusion in parsed.exclusions:
                    office = (
                        "NAMK_LOCAL_GOVERNMENT_MEMBER",
                        exclusion["organizationCode"],
                    )
                    if office in seen_local_offices:
                        raise ValueError("duplicate_office")
                    seen_local_offices.add(office)
            if accounted >= expected or adapter in {"parties", "gaok"}:
                break
            if not parsed.records and not (adapter == "namk" and parsed.exclusions):
                errors.append({"page": page, "reason": "unexpected_empty_page"})
                break
        except Exception as error:
            reason = (
                str(error)
                if str(error) in {"duplicate_record", "duplicate_office"}
                else type(error).__name__
            )
            errors.append({"page": page, "reason": reason})
            if not observations or observations[-1].get("page") != page:
                observations.append(
                    {"url": url, "observedAt": stamp, "page": page, "status": "failed"}
                )
            break
        if delay:
            time.sleep(delay)
    # Co-leaders make person count differ from registered organization count.
    complete = (
        not errors
        and expected is not None
        and (adapter == "parties" or accounted == expected)
    )
    result = {
        "jobId": job_id,
        "sourceSpec": source,
        "expectedCount": expected,
        "recordCount": len(records),
        "complete": complete,
        "records": records,
        "observations": observations,
        "errors": errors,
        "exclusions": exclusions,
        "currentness": "source_current_roster",
        "publication": "pending_operator_review",
    }
    if adapter == "gaok":
        result["universeMethod"] = "published_body_card_count"
        result["scopeNote"] = (
            "Published association member list; not an independently verified statutory universe."
        )
    if adapter == "namk":
        result["universeMethod"] = "source_reported_office_records"
        result["unresolvedOfficeholderCount"] = sum(
            item["status"] == "unknown_officeholder" for item in exclusions
        )
        result["vacancyCount"] = sum(item["status"] == "vacant" for item in exclusions)
    if adapter == "goryeong_statement":
        result["currentness"] = "source_dated_office_statement"
        result["scopeNote"] = (
            "Dated official acting-role statement; current role requires separate confirmation."
        )
    private_write(
        receipt,
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2).encode(),
    )
    return result
