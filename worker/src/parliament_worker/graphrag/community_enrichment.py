"""Select fixed child claims to enrich claim-free parent communities."""

from copy import deepcopy
from typing import Any

from parliament_worker.graphrag.inputs import fingerprint
from parliament_worker.graphrag.output_contract import _object
from parliament_worker.graphrag.prompts import GROUP_ID_VERSION, PROMPT_VERSION, request
from parliament_worker.graphrag.source_safety import contains_contact
from parliament_worker.graphrag.store import GraphStore

SELECTION_CONTRACT = "parliament-community-evidence-selection-v1"


def build_selection_request(
    parent: dict[str, Any], children: list[dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Ask the model to choose IDs without letting it rewrite facts or quotes.

    Args:
        parent: Current parent artifact with at least one claim-free group.
        children: Its pinned direct child community artifacts.

    Returns:
        A strict inference body and private, immutable candidate context.

    Raises:
        ValueError: If the parent and supplied child versions do not agree.
    """
    payload = parent["payload"]
    if (
        payload.get("level", 0) < 1
        or payload.get("reportStatus")
        in {
            "evidence_selected",
            "evidence_partially_selected",
            "evidence_selection_exhausted",
        }
        or not any(not group["claims"] for group in payload["groups"])
    ):
        raise ValueError("community is not an eligible parent")
    pinned = parent["dependency"].get("children", [])
    expected = {(item["kind"], item["key"], item["version"]) for item in pinned}
    actual = {(item["kind"], item["key"], item["version"]) for item in children}
    if (
        expected != actual
        or len(pinned) != len(children)
        or any(item["kind"] != "community" for item in children)
    ):
        raise ValueError("community child version mismatch")
    child_groups = {}
    for child in children:
        for group in child["payload"]["groups"]:
            if group["id"] in child_groups:
                raise ValueError("duplicate child community group")
            child_groups[group["id"]] = group

    candidates: dict[str, dict[str, Any]] = {}
    presented = []
    for index, group in enumerate(payload["groups"], 1):
        group_alias = f"G{index}"
        candidate_aliases = []
        if not group["claims"]:
            for member in group["members"]:
                if member not in child_groups:
                    raise ValueError("unknown parent community member")
                for claim in child_groups[member]["claims"]:
                    text, evidence = claim.get("text"), claim.get("evidence")
                    if (
                        not isinstance(text, str)
                        or not isinstance(evidence, dict)
                        or not isinstance(evidence.get("text"), str)
                        or contains_contact(text)
                        or contains_contact(evidence["text"])
                    ):
                        continue
                    alias = f"C{len(candidates) + 1}"
                    candidates[alias] = {
                        "group": group_alias,
                        "claim": deepcopy(claim),
                    }
                    candidate_aliases.append(alias)
        presented.append(
            {
                "id": group_alias,
                "title": (
                    group["title"] if not contains_contact(group["title"]) else ""
                ),
                "candidates": [
                    {"id": alias, "text": candidates[alias]["claim"]["text"]}
                    for alias in candidate_aliases
                ],
            }
        )
    if not candidates:
        raise ValueError("community has no safe child claims")

    body = request(
        "select evidence IDs for existing community groups",
        {
            "groups": presented,
            "rules": (
                "For each group select 0 to 2 of its listed candidate IDs. "
                "Choose only facts relevant to that group's members. "
                "Return IDs only; never write or paraphrase a fact, title, quote, "
                "person role, or political position. Empty selection is valid."
            ),
        },
        output_tokens=160,
    )
    properties = {}
    for group in presented:
        allowed = [candidate["id"] for candidate in group["candidates"]]
        properties[group["id"]] = {
            "type": "array",
            "items": {"type": "string", **({"enum": allowed} if allowed else {})},
            "minItems": 0,
            "maxItems": min(2, len(allowed)),
        }
    body["response_format"] = {
        "type": "json_schema",
        "json_schema": {
            "name": "parliament_community_evidence_selection_v1",
            "strict": True,
            "schema": _object({"selected": _object(properties)}),
        },
    }
    context = {
        "output_contract": SELECTION_CONTRACT,
        "prior_report_version": parent["version"],
        "prior_payload": deepcopy(payload),
        "candidates": candidates,
    }
    return body, context


def materialize_evidence_selection(
    output: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Copy selected child claims and proofs without model-written assertions.

    Args:
        output: Schema-constrained mapping from parent group to child claim IDs.
        context: Fixed report and candidate claims from request creation.

    Returns:
        Private parent report payload with a distinct evidence-selection status.

    Raises:
        ValueError: If any selection is missing, duplicated, or outside its group.
    """
    groups = deepcopy(context["prior_payload"]["groups"])
    selected = output.get("selected")
    expected = {f"G{index}" for index in range(1, len(groups) + 1)}
    if not isinstance(selected, dict) or set(selected) != expected:
        raise ValueError("community selection group coverage incomplete")
    used: set[str] = set()
    for index, group in enumerate(groups, 1):
        alias = f"G{index}"
        chosen = selected[alias]
        if not isinstance(chosen, list) or len(chosen) > 2:
            raise ValueError("invalid community claim selection")
        if group["claims"]:
            if chosen:
                raise ValueError("existing community claim cannot be replaced")
            continue
        claims = []
        for claim_alias in chosen:
            if not isinstance(claim_alias, str):
                raise ValueError("invalid community claim selection")
            candidate = context["candidates"].get(claim_alias)
            if candidate is None or candidate["group"] != alias or claim_alias in used:
                raise ValueError("community claim belongs to another group")
            used.add(claim_alias)
            claims.append(deepcopy(candidate["claim"]))
        group["claims"] = claims
        group["summary"] = " ".join(claim["text"] for claim in claims)
        group["reportStatus"] = "evidence_selected" if claims else "membership_only"
    covered = sum(bool(group["claims"]) for group in groups)
    report = deepcopy(context["prior_payload"])
    report["groups"] = groups
    report["public"] = False
    report["reportStatus"] = (
        "evidence_selected"
        if covered == len(groups)
        else (
            "evidence_partially_selected" if covered else "evidence_selection_exhausted"
        )
    )
    return report


def plan_evidence_enrichments(
    store: GraphStore, model_signature: str, capacity: int
) -> int:
    """Persist one evidence-ID selection for each current claim-free parent.

    Args:
        store: Durable private graph state.
        model_signature: Pinned repository and model revision.
        capacity: Maximum pending inference jobs.

    Returns:
        Number of newly persisted inference intentions.
    """
    jobs = store.jobs()
    room = capacity - sum(
        job["state"] in {"planned", "deferred", "submitting", "polling"} for job in jobs
    )
    if room <= 0:
        return 0
    known = {(job["kind"], job["key"]) for job in jobs}
    reports = store.artifacts("community")
    by_key = {report["key"]: report for report in reports}
    eligible = []
    for parent in reports:
        payload = parent["payload"]
        dependency = parent["dependency"]
        if (
            payload.get("level", 0) < 1
            or dependency.get("model_signature") != model_signature
            or dependency.get("prompt_version") != PROMPT_VERSION
            or dependency.get("group_id_version") != GROUP_ID_VERSION
        ):
            continue
        pinned = dependency.get("children", [])
        children = [by_key.get(item["key"]) for item in pinned]
        if any(
            child is None
            or child["kind"] != "community"
            or child["version"] != item["version"]
            for child, item in zip(children, pinned, strict=True)
        ):
            continue
        try:
            body, context = build_selection_request(parent, children)
        except ValueError:
            continue
        context.update(dependency, artifact_key=parent["key"])
        key = fingerprint(
            [SELECTION_CONTRACT, parent["key"], parent["version"], model_signature]
        )
        eligible.append((payload["level"], key, body, context))
    if not eligible:
        return 0
    first_level = min(item[0] for item in eligible)
    planned = []
    for level, key, body, context in eligible:
        if level != first_level or ("community", key) in known:
            continue
        planned.append(
            {"kind": "community", "key": key, "request": body, "context": context}
        )
        if len(planned) >= room:
            break
    if planned:
        store.enqueue_many(planned)
    return len(planned)
