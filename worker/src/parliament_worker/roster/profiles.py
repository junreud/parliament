"""Refresh operator-selected office profiles and detect name/markup changes safely."""

import hashlib
import json
import re
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from parliament_worker.http import validate_official_url
from parliament_worker.knowledge.files import private_read, private_write


def find_name_surface(text: str, canonical: str) -> str | None:
    """Match an expected profile name while preserving source letter spacing."""
    letters = "".join(canonical.split())
    if not 1 <= len(letters) <= 50:
        raise ValueError("invalid expected profile name")
    pattern = r"(?<!\w)" + r"\s*".join(re.escape(c) for c in letters) + r"(?!\w)"
    match = re.search(pattern, text)
    return match.group(0) if match else None


def collect_profiles(
    specs: list[dict[str, Any]],
    fetcher: Callable[[str], bytes],
    output: Path,
    job_id: str,
    *,
    delay: float = 0.0,
) -> dict[str, Any]:
    """Collect source-local candidates while keeping changed identities private.

    Args:
        specs: Explicit office, expected source name, exact selectors and URL.
        fetcher: URL/DNS/redirect validating public-source fetcher.
        output: Private raw and run destination.
        job_id: Explicit replay identifier.
        delay: Interval between requests; no recursive site crawling.

    Returns:
        Candidates and observations; source-local identities and usage stay
        unreviewed. A changed name or markup is recorded for operator review.
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_id) or not 1 <= len(specs) <= 200:
        raise ValueError("invalid profile collection bounds")
    if not 0 <= delay <= 10:
        raise ValueError("invalid profile request delay")
    identities = set()
    for spec in specs:
        identifier = spec.get("id", "")
        if (
            not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", identifier)
            or identifier in identities
        ):
            raise ValueError("invalid or duplicate office profile identity")
        identities.add(identifier)
        validate_official_url(spec["sourceUrl"])
        for field in [
            "expectedName",
            "organizationCode",
            "organizationName",
            "position",
        ]:
            if (
                not isinstance(spec.get(field), str)
                or not 1 <= len(spec[field]) <= 4000
            ):
                raise ValueError("invalid profile selector or office field")
        list_path = spec.get("jsonListPath")
        if list_path is not None:
            if (
                not isinstance(list_path, list)
                or not 1 <= len(list_path) <= 4
                or any(
                    not isinstance(key, str)
                    or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", key)
                    for key in list_path
                )
                or any(
                    spec.get(field) is not None
                    for field in (
                        "nameSelector",
                        "contextSelector",
                        "jsonTextPath",
                        "nameAttribute",
                        "nameTemplate",
                        "tableCaptionSelector",
                    )
                )
            ):
                raise ValueError("invalid bounded JSON office list")
            for field in ("jsonNameField", "jsonPositionField"):
                value = spec.get(field)
                if not isinstance(value, str) or not re.fullmatch(
                    r"[A-Za-z0-9_-]{1,100}", value
                ):
                    raise ValueError("invalid JSON office field")
                if re.search(r"TEL|FAX|PHONE|EMAIL|MAIL|ADDR|CONTACT", value, re.I):
                    raise ValueError("JSON contact field cannot be selected")
            if spec["jsonNameField"] == spec["jsonPositionField"]:
                raise ValueError("JSON office fields must be distinct")
        else:
            for field in ("nameSelector", "contextSelector"):
                value = spec.get(field)
                if not isinstance(value, str) or not 1 <= len(value) <= 4000:
                    raise ValueError("invalid profile selector or office field")
            caption_selector = spec.get("tableCaptionSelector")
            if caption_selector is not None and (
                not isinstance(caption_selector, str)
                or not 1 <= len(caption_selector) <= 4000
            ):
                raise ValueError("invalid table caption selector")
        if spec.get("nameAttribute") not in (None, "alt", "title"):
            raise ValueError("unsupported explicit source name attribute")
        template = spec.get("nameTemplate")
        if template is not None and (
            not isinstance(template, str)
            or not 1 <= len(template) <= 200
            or template.count("{name}") != 1
            or template.count("{") != 1
            or template.count("}") != 1
            or spec["position"] not in template
        ):
            raise ValueError("invalid explicit office name template")
        if spec.get("licenseStatus", "unknown") not in ("unknown", "restricted"):
            raise ValueError("profile collection cannot approve source usage")
        json_path = spec.get("jsonTextPath")
        if json_path is not None and (
            not isinstance(json_path, list)
            or not 1 <= len(json_path) <= 4
            or any(
                not isinstance(key, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", key)
                for key in json_path
            )
        ):
            raise ValueError("invalid bounded JSON text field")
    receipt = output / "runs" / job_id / "profiles.json"
    if receipt.exists():
        prior = json.loads(private_read(receipt, max_bytes=20_000_000))
        if prior["sourceSpecs"] != specs:
            raise ValueError("profile job replay source conflict")
        return prior
    observations, records = [], []
    for spec in specs:
        list_path = spec.get("jsonListPath")
        template = spec.get("nameTemplate")
        stamp = datetime.now(timezone.utc).isoformat()
        observed = {"id": spec["id"], "url": spec["sourceUrl"], "observedAt": stamp}
        try:
            raw = fetcher(spec["sourceUrl"])
            raw_hash = hashlib.sha256(raw).hexdigest()
            private_write(output / "raw" / (raw_hash + ".bin"), raw)
            observed["rawHash"] = raw_hash
            context, context_surface, locator, raw_format = "", None, "", "html"
            if list_path is not None:
                value = json.loads(raw)
                for key in list_path:
                    if not isinstance(value, dict) or key not in value:
                        raise ValueError("missing JSON office list")
                    value = value[key]
                if not isinstance(value, list) or len(value) > 2000:
                    raise ValueError("invalid JSON office list")
                matches = [
                    (index, row)
                    for index, row in enumerate(value)
                    if isinstance(row, dict)
                    and row.get(spec["jsonNameField"]) == spec["expectedName"]
                ]
                if not matches:
                    observed["status"] = "identity_changed"
                elif len(matches) != 1:
                    observed["status"] = "ambiguous_identity"
                else:
                    index, row = matches[0]
                    if row.get(spec["jsonPositionField"]) != spec["position"]:
                        observed["status"] = "role_changed"
                    else:
                        context_surface = row[spec["jsonNameField"]]
                        context = context_surface + " " + row[spec["jsonPositionField"]]
                        locator = (
                            "JSON $."
                            + ".".join(list_path)
                            + f"[{index}] fields "
                            + spec["jsonNameField"]
                            + ","
                            + spec["jsonPositionField"]
                        )
                        raw_format = "json"
                        observed["status"] = "success"
            else:
                content = raw
                prefix = "html:"
                json_path = spec.get("jsonTextPath")
                if json_path:
                    value = json.loads(raw)
                    for key in json_path:
                        if not isinstance(value, dict) or key not in value:
                            raise ValueError("missing JSON profile text field")
                        value = value[key]
                    if not isinstance(value, str):
                        raise ValueError("invalid JSON profile text field")
                    content = value.encode()
                    prefix = "json:/" + "/".join(json_path) + "|html:"
                soup = BeautifulSoup(content, "html.parser")
                names = soup.select(spec["nameSelector"])
                contexts = soup.select(spec["contextSelector"])
                caption_selector = spec.get("tableCaptionSelector")
                captions = soup.select(caption_selector) if caption_selector else []
                table = contexts[0].find_parent("table") if len(contexts) == 1 else None
                caption_text = (
                    captions[0].get_text(" ", strip=True) if len(captions) == 1 else ""
                )
                invalid_caption = bool(caption_selector) and (
                    len(captions) != 1
                    or table is None
                    or captions[0].parent is not table
                    or not 1 <= len(caption_text) <= 300
                )
                if len(names) != 1 or len(contexts) != 1 or invalid_caption:
                    observed["status"] = "markup_changed"
                else:
                    attribute = spec.get("nameAttribute")
                    text = (
                        names[0].get(attribute, "")
                        if attribute
                        else names[0].get_text(" ", strip=True)
                    )
                    context = contexts[0].get_text(" ", strip=True)
                    if caption_selector:
                        context = caption_text + " " + context
                    if template is None:
                        surface = find_name_surface(text, spec["expectedName"])
                        context_surface = find_name_surface(
                            context, spec["expectedName"]
                        )
                    else:
                        phrase = template.replace("{name}", spec["expectedName"])
                        surface = (
                            spec["expectedName"] if text.count(phrase) == 1 else None
                        )
                        context_surface = (
                            spec["expectedName"] if context.count(phrase) == 1 else None
                        )
                    if surface is None:
                        embedded = "".join(spec["expectedName"].split()) in "".join(
                            text.split()
                        )
                        observed["status"] = (
                            "name_surface_review_required"
                            if embedded
                            else "identity_changed"
                        )
                    elif attribute or context_surface is None:
                        observed["status"] = "attribute_review_required"
                    else:
                        locator = prefix + (
                            caption_selector + " + " + spec["contextSelector"]
                            if caption_selector
                            else spec["contextSelector"]
                        )
                        raw_format = "json" if json_path else "html"
                        observed["status"] = "success"
            if observed["status"] == "success":
                source_identity = (
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
                records.append(
                    {
                        "namespace": "KR_OFFICE_PROFILE_CANDIDATE",
                        "sourceRecordId": source_identity,
                        "name": spec["expectedName"],
                        "nameSurface": context_surface,
                        "position": spec["position"],
                        "organizationCode": spec["organizationCode"],
                        "organizationNamespace": spec.get(
                            "organizationNamespace", "MOIS_GOVERNMENT_ORGANIZATION"
                        ),
                        "organizationName": spec["organizationName"],
                        "identityStatus": "source_local_candidate",
                        "currentness": spec.get("currentness", "source_profile"),
                        "observedAt": stamp,
                        "sourceUrl": spec["sourceUrl"],
                        "rawHash": raw_hash,
                        "format": raw_format,
                        "licenseStatus": spec.get("licenseStatus", "unknown"),
                        "excerpt": context,
                        "evidenceLocator": locator,
                        **{
                            field: spec[field]
                            for field in (
                                "sourcePublishedAt",
                                "qualificationObservedAt",
                                "datePrecision",
                            )
                            if spec.get(field) is not None
                        },
                    }
                )
        except Exception as error:
            observed["status"] = "failed"
            observed["errorType"] = type(error).__name__
        observations.append(observed)
        if delay:
            time.sleep(delay)
    result = {
        "jobId": job_id,
        "sourceSpecs": specs,
        "records": records,
        "observations": observations,
        "complete": all(o["status"] == "success" for o in observations),
        "publication": "pending_operator_review",
    }
    private_write(
        receipt,
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2).encode(),
    )
    return result
