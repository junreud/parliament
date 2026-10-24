"""Request missing source-bound office links without inventing role decisions."""

import json
import re
from typing import Any

from parliament_worker.graphrag.index import source_dependency
from parliament_worker.graphrag.inputs import canonical, fingerprint
from parliament_worker.graphrag.output_contract import (
    DIRECTIONAL_CONTRACT,
    directional_extraction_contract,
)
from parliament_worker.graphrag.prompts import PROMPT_VERSION, extraction
from parliament_worker.graphrag.source_forms import source_form
from parliament_worker.graphrag.store import GraphStore

REPAIR_VERSION = "source-spaced-office-v1"
TYPED_REPAIR_VERSION = "source-typed-office-v1"
CROSS_UNIT_REPAIR_VERSION = "source-cross-unit-office-v1"
TYPED_LIST_REPAIR_VERSION = "source-typed-list-office-v1"
TYPED_LIST_CATEGORIES = {
    "roster_NAMK_OFFICEHOLDER_SNAPSHOT": "기초단체장 명부 표기",
    "roster_NEC_PARTY_HOLDER_SNAPSHOT": "대표 명부 근거",
}
OFFICE_CUE = re.compile(
    r"부위원장|위원장|장관|차관|국무총리|대통령|실장|국장|청장|처장|시장|군수|구청장|대표(?!발의)"
)
ACTIVE_STATES = frozenset({"planned", "deferred", "submitting", "polling"})


def validate_composite_source_proof(
    context: dict[str, Any], source: dict[str, Any]
) -> None:
    """Check joined evidence against the immutable current source units.

    Args:
        context: Persisted model request with joined proof units.
        source: Source revision pinned by the request dependency.

    Raises:
        ValueError: A joined span cannot be reconstructed from source units.
    """
    if context.get("sources") != [source_dependency(source)]:
        raise ValueError("composite source proof dependency mismatch")
    originals = source["payload"]["units"]
    indices = {unit["id"]: index for index, unit in enumerate(originals)}
    for joined in context["units"].values():
        unit_ids = joined.get("sourceUnitIds")
        if unit_ids is None:
            continue
        if (
            not isinstance(unit_ids, list)
            or len(unit_ids) < 2
            or len(set(unit_ids)) != len(unit_ids)
            or any(unit_id not in indices for unit_id in unit_ids)
        ):
            raise ValueError("composite source proof invalid units")
        positions = [indices[unit_id] for unit_id in unit_ids]
        if positions != list(range(positions[0], positions[0] + len(positions))):
            raise ValueError("composite source proof noncontiguous units")
        group = [originals[index] for index in positions]
        first = group[0]
        if any(
            any(
                item[field] != first[field]
                for field in (
                    "documentId",
                    "documentVersion",
                    "extractionVersion",
                    "segmentId",
                )
            )
            or previous["end"] != item["start"]
            for previous, item in zip(group, group[1:])
        ) or any(
            joined[field] != first[field]
            for field in (
                "documentId",
                "documentVersion",
                "extractionVersion",
                "segmentId",
            )
        ):
            raise ValueError("composite source proof version mismatch")
        start = joined["start"] - first["start"]
        text = "".join(item["text"] for item in group)
        if (
            start < 0
            or joined["end"] != joined["start"] + len(joined["text"])
            or start + len(joined["text"]) > len(text)
            or text[start : start + len(joined["text"])] != joined["text"]
        ):
            raise ValueError("composite source proof text mismatch")


def validate_typed_list_source_proof(
    context: dict[str, Any], source: dict[str, Any]
) -> None:
    """Recheck a role-list title and row against their pinned source revision.

    Args:
        context: Persisted typed-list inference request.
        source: Current immutable source and document metadata.

    Raises:
        ValueError: The title, row, category, or source dependency changed.
    """
    if context.get("sources") != [source_dependency(source)]:
        raise ValueError("typed list source proof dependency mismatch")
    document = source["payload"]["document"]
    marker = TYPED_LIST_CATEGORIES.get(document["sourceKey"])
    if not marker or marker not in document["title"]:
        raise ValueError("typed list source proof category mismatch")
    joined = context.get("units", {}).get("U1")
    if not isinstance(joined, dict) or joined.get("sourceTitle") != document["title"]:
        raise ValueError("typed list source proof title mismatch")
    original = next(
        (unit for unit in source["payload"]["units"] if unit["id"] == joined.get("id")),
        None,
    )
    if original is None or joined != {**original, "sourceTitle": document["title"]}:
        raise ValueError("typed list source proof row mismatch")


def _cross_unit_window(
    group: list[dict[str, Any]], person_name: str, organization_name: str
) -> tuple[dict[str, Any], str, str] | None:
    """Select one contiguous, source-bound quote spanning a split boundary."""
    first = group[0]
    if any(
        unit["segmentId"] != first["segmentId"]
        or unit["documentId"] != first["documentId"]
        or unit["documentVersion"] != first["documentVersion"]
        or unit["extractionVersion"] != first["extractionVersion"]
        or previous["end"] != unit["start"]
        for previous, unit in zip(group, group[1:])
    ):
        return None
    text = "".join(unit["text"] for unit in group)
    person_form = source_form(text, person_name)
    organization_form = source_form(text, organization_name)
    if not person_form or not organization_form:
        return None
    person_start = text.index(person_form)
    organization_start = text.index(organization_form)
    candidates = []
    for cue in OFFICE_CUE.finditer(text):
        left = min(person_start, organization_start, cue.start())
        right = max(
            person_start + len(person_form),
            organization_start + len(organization_form),
            cue.end(),
        )
        candidates.append((len(text[left:right].encode()), left, right))
    if not candidates:
        return None
    _, core_left, core_right = min(candidates)
    if not any(
        core_left < unit["end"] - first["start"] < core_right for unit in group[:-1]
    ):
        return None
    left = max(0, core_left - 40)
    right = min(len(text), core_right + 40)
    while len(text[left:right].encode()) > 850 and (
        left < core_left or right > core_right
    ):
        if right - core_right > core_left - left:
            right -= 1
        else:
            left += 1
    if len(text[left:right].encode()) > 850:
        return None
    start, end = first["start"] + left, first["start"] + right
    if not any(unit["start"] < end and unit["end"] > start for unit in group[1:]):
        return None
    coordinates = {
        key: first[key]
        for key in ("documentId", "documentVersion", "extractionVersion", "segmentId")
    }
    window = {
        **first,
        "id": "tu_" + fingerprint([coordinates, start, end, CROSS_UNIT_REPAIR_VERSION]),
        "start": start,
        "end": end,
        "text": text[left:right],
        "sourceUnitIds": [unit["id"] for unit in group],
    }
    return window, person_form, organization_form


def _repair_request(
    source: dict[str, Any],
    unit: dict[str, Any],
    person: dict[str, Any],
    organization: dict[str, Any],
    person_form: str,
    organization_form: str,
    list_title: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Offer the model exact source spellings while retaining stable IDs."""
    reduced = {"payload": {"entities": [person, organization]}}
    body, context = extraction(reduced, unit)
    data = json.loads(body["messages"][-1]["content"])
    forms = {}
    for item in data["known"]:
        entity = context["aliases"][item["id"]]
        form = person_form if entity["id"] == person["id"] else organization_form
        item["name"] = form
        forms[item["id"]] = form
    data["types"] = ["holds_office"]
    if list_title is None:
        data["rules"] = (
            "Return a person-to-organization holds_office relation only when this "
            "source unit explicitly states the person's office in that organization. "
            "Names in navigation, historical careers, and co-occurrence alone do not "
            "establish a current role. Return entities=[] and relations=[] when uncertain."
        )
    else:
        data["document"] = {"title": list_title}
        data["rules"] = (
            "Use the official list category in document.title together with this "
            "exact list row to decide whether the named person is listed for the "
            "named organization. A title or two names alone is insufficient. "
            "This is a source-time listed role, not proof of current office. "
            "Return entities=[] and relations=[] when uncertain."
        )
    body["messages"][-1]["content"] = canonical(data).decode()
    body = directional_extraction_contract(body)
    body["max_completion_tokens"] = 384
    schema = body["response_format"]["json_schema"]["schema"]
    schema["properties"]["entities"]["maxItems"] = 0
    context.update(sourceForms=forms, output_contract=DIRECTIONAL_CONTRACT)
    if list_title is not None:
        context["units"]["U1"] = {**unit, "sourceTitle": list_title}
    return body, context


def plan_office_repairs(
    store: GraphStore,
    model_signature: str,
    capacity: int = 256,
    *,
    typed_pairs: set[tuple[str, str]] | None = None,
) -> int:
    """Queue model checks for explicit, source-bound office roles.

    Args:
        store: Private source, artifact, and job repository.
        model_signature: Pinned actual model repository and revision.
        capacity: Shared planned plus in-flight job ceiling.
        typed_pairs: Independently structured tenure pairs; exact names may be
            retried only for these pairs. None preserves legacy spacing repairs.

    Returns:
        Number of new immutable inference requests scheduled.
    """
    if capacity < 1:
        raise ValueError("invalid repair capacity")
    jobs = store.jobs()
    room = capacity - sum(job["state"] in ACTIVE_STATES for job in jobs)
    if room <= 0:
        return 0
    known = {(job["kind"], job["key"]) for job in jobs}
    artifacts = store.artifacts("graph")
    graphs = {artifact["key"]: artifact for artifact in artifacts}
    office_pairs = {
        (edge["source"], edge["target"])
        for artifact in artifacts
        for edge in artifact["payload"].get("edges", [])
        if edge["type"] == "holds_office"
    }
    planned = []
    for source in store.sources():
        dependency = source_dependency(source)
        people = [
            entity
            for entity in source["payload"]["entities"]
            if entity["kind"] == "person"
        ]
        organizations = [
            entity
            for entity in source["payload"]["entities"]
            if entity["kind"] == "organization"
        ]
        if not people or not organizations:
            continue
        planned_pairs: set[tuple[str, str]] = set()
        for unit in source["payload"]["units"]:
            text = unit["text"]
            list_marker = TYPED_LIST_CATEGORIES.get(
                source["payload"]["document"]["sourceKey"]
            )
            list_title = source["payload"]["document"]["title"]
            typed_list = (
                typed_pairs is not None
                and list_marker is not None
                and list_marker in list_title
            )
            if not OFFICE_CUE.search(text) and not typed_list:
                continue
            original = graphs.get(f"{source['scope']}:{unit['id']}")
            if not original or original["dependency"] != {
                "sources": [dependency],
                "model_signature": model_signature,
                "prompt_version": PROMPT_VERSION,
            }:
                continue
            for person in people:
                person_form = source_form(text, person["name"])
                if not person_form:
                    continue
                for organization in organizations:
                    organization_form = source_form(text, organization["name"])
                    pair = (person["id"], organization["id"])
                    typed = typed_pairs is not None and pair in typed_pairs
                    if (
                        not organization_form
                        or typed_pairs is not None
                        and not typed
                        or not typed
                        and (person_form, organization_form)
                        == (person["name"], organization["name"])
                        or pair in office_pairs
                    ):
                        continue
                    contextual_list = typed_list and not OFFICE_CUE.search(text)
                    repair_version = (
                        TYPED_LIST_REPAIR_VERSION
                        if contextual_list
                        else TYPED_REPAIR_VERSION if typed else REPAIR_VERSION
                    )
                    key = fingerprint(
                        [
                            dependency,
                            unit["id"],
                            person["id"],
                            organization["id"],
                            model_signature,
                            PROMPT_VERSION,
                            repair_version,
                        ]
                    )
                    if ("extract", key) in known:
                        continue
                    body, context = _repair_request(
                        source,
                        unit,
                        person,
                        organization,
                        person_form,
                        organization_form,
                        list_title if contextual_list else None,
                    )
                    context.update(
                        sources=[dependency],
                        artifact_key=(
                            f"{source['scope']}:{unit['id']}:{repair_version}:"
                            f"{person['id']}:{organization['id']}"
                        ),
                        model_signature=model_signature,
                        prompt_version=PROMPT_VERSION,
                        repair_version=repair_version,
                    )
                    planned.append(
                        {
                            "kind": "extract",
                            "key": key,
                            "request": body,
                            "context": context,
                        }
                    )
                    planned_pairs.add(pair)
                    known.add(("extract", key))
                    if len(planned) >= room:
                        store.enqueue_many(planned)
                        return len(planned)
        if typed_pairs is None:
            continue
        units = sorted(
            source["payload"]["units"],
            key=lambda item: (item["segmentId"], item["start"]),
        )
        for index in range(len(units) - 1):
            for width in (2, 3):
                group = units[index : index + width]
                if len(group) != width or any(
                    not graphs.get(f"{source['scope']}:{unit['id']}")
                    or graphs[f"{source['scope']}:{unit['id']}"]["dependency"]
                    != {
                        "sources": [dependency],
                        "model_signature": model_signature,
                        "prompt_version": PROMPT_VERSION,
                    }
                    for unit in group
                ):
                    continue
                for person in people:
                    for organization in organizations:
                        pair = (person["id"], organization["id"])
                        if (
                            pair not in typed_pairs
                            or pair in office_pairs
                            or pair in planned_pairs
                        ):
                            continue
                        window = _cross_unit_window(
                            group, person["name"], organization["name"]
                        )
                        if window is None:
                            continue
                        unit, person_form, organization_form = window
                        key = fingerprint(
                            [
                                dependency,
                                unit["id"],
                                *pair,
                                model_signature,
                                PROMPT_VERSION,
                                CROSS_UNIT_REPAIR_VERSION,
                            ]
                        )
                        if ("extract", key) in known:
                            continue
                        body, context = _repair_request(
                            source,
                            unit,
                            person,
                            organization,
                            person_form,
                            organization_form,
                        )
                        context.update(
                            sources=[dependency],
                            artifact_key=(
                                f"{source['scope']}:{unit['id']}:"
                                f"{CROSS_UNIT_REPAIR_VERSION}:{person['id']}:"
                                f"{organization['id']}"
                            ),
                            model_signature=model_signature,
                            prompt_version=PROMPT_VERSION,
                            repair_version=CROSS_UNIT_REPAIR_VERSION,
                        )
                        planned.append(
                            {
                                "kind": "extract",
                                "key": key,
                                "request": body,
                                "context": context,
                            }
                        )
                        planned_pairs.add(pair)
                        known.add(("extract", key))
                        if len(planned) >= room:
                            store.enqueue_many(planned)
                            return len(planned)
    if planned:
        store.enqueue_many(planned)
    return len(planned)
