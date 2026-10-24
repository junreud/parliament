"""Reduce long global answers by selecting pinned claims without rewriting them."""

import json
from copy import deepcopy
from typing import Any
from urllib.parse import urlparse

from parliament_worker.graphrag.inputs import canonical
from parliament_worker.graphrag.prompts import request

CLAIM_SELECTION_CONTRACT = "parliament-answer-claim-selection-v1"
SOURCE_GROUP_SELECTION_CONTRACT = "parliament-answer-source-groups-v2"
SELECTION_INVARIANT = (
    " Set insufficient=true only when selected=[]. If any supplied claim ID is"
    " selected, set insufficient=false, even if the selection covers only part"
    " of the question. Never combine nonempty selected with insufficient=true."
)
GROUP_SELECTION_UNIQUENESS = (
    " Never repeat a claim ID in hostChoices or extra. Every extra ID must"
    " differ from every hostChoices ID and every other extra ID. If no distinct"
    " useful extra claim remains, return extra=[]."
)
REQUESTED_FACETS = (
    ("original_bill", ("원안",)),
    ("alternative_bill", ("대안",)),
    ("government_followup", ("후속 발표", "후속 조치", "정부 발표")),
)


def selection_request(
    question: str,
    claims: list[dict[str, Any]],
    *,
    source_facets: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Send concise claim text while retaining exact evidence only in local context."""
    aliases = {f"C{index + 1}": claim for index, claim in enumerate(claims)}
    if not aliases:
        raise ValueError("claim selection needs candidates")
    hosts = {
        key: urlparse(claim.get("evidence", {}).get("sourceUrl", "")).hostname
        for key, claim in aliases.items()
    }
    source_facets = source_facets or {}
    facets = {
        key: source_facets.get(claim.get("evidence", {}).get("sourceUrl", ""))
        for key, claim in aliases.items()
    }
    required_facets = [
        facet
        for facet, phrases in REQUESTED_FACETS
        if any(phrase in question for phrase in phrases) and facet in facets.values()
    ]
    distinct_hosts = sorted({host for host in hosts.values() if host})
    required_hosts = (
        distinct_hosts
        if not required_facets
        and all(hosts.values())
        and 2 <= len(distinct_hosts) <= 4
        and any(term in question for term in ("각각", "비교", "각 문서"))
        else []
    )
    required_groups = required_facets or required_hosts
    host_aliases = {
        f"H{index + 1}": [
            key
            for key in aliases
            if (facets[key] if required_facets else hosts[key]) == group
        ]
        for index, group in enumerate(required_groups)
    }
    group_by_claim = {
        key: alias for alias, members in host_aliases.items() for key in members
    }
    body = request(
        "select grounded claims",
        {
            "question": question,
            "candidateClaims": [
                {
                    "id": key,
                    "text": claim["text"],
                    "sourceHost": hosts[key] or "",
                    "sourceGroup": group_by_claim.get(key, ""),
                }
                for key, claim in aliases.items()
            ],
            "rules": (
                "Select up to four supplied claim IDs that most directly answer "
                "the question. Do not invent, rewrite or infer any fact. Return "
                "an empty selection only if none answers it."
                + (
                    " Fill each required hostChoices slot with a claim ID from"
                    " that sourceGroup. Then choose up to the remaining extra"
                    " claims. Do not omit a represented source host."
                    + GROUP_SELECTION_UNIQUENESS
                    if required_groups
                    else ""
                )
                + ("" if required_groups else SELECTION_INVARIANT)
            ),
        },
        output_tokens=128,
    )
    if required_groups:
        schema_name = "parliament_source_group_selection_v2"
        schema = {
            "type": "object",
            "properties": {
                "hostChoices": {
                    "type": "object",
                    "properties": {
                        alias: {"type": "string", "enum": choices}
                        for alias, choices in host_aliases.items()
                    },
                    "required": list(host_aliases),
                    "additionalProperties": False,
                },
                "extra": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(aliases)},
                    "maxItems": 4 - len(required_groups),
                },
            },
            "required": ["hostChoices", "extra"],
            "additionalProperties": False,
        }
    else:
        schema_name = "parliament_claim_selection_v1"
        schema = {
            "type": "object",
            "properties": {
                "selected": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(aliases)},
                    "maxItems": 4,
                },
                "insufficient": {"type": "boolean"},
            },
            "required": ["selected", "insufficient"],
            "additionalProperties": False,
        }
    body["response_format"] = {
        "type": "json_schema",
        "json_schema": {"name": schema_name, "strict": True, "schema": schema},
    }
    return body, {
        "output_contract": (
            SOURCE_GROUP_SELECTION_CONTRACT
            if required_groups
            else CLAIM_SELECTION_CONTRACT
        ),
        "selectionClaims": aliases,
        "requiredHosts": required_hosts,
        "requiredFacets": required_facets,
        "sourceFacets": {
            claim["evidence"]["sourceUrl"]: facets[key]
            for key, claim in aliases.items()
            if facets[key]
        },
        "hostAliases": host_aliases,
    }


def selection_retry_request(body: dict[str, Any]) -> dict[str, Any]:
    """Clarify the selection flag while preserving the pinned claim-ID schema.

    Args:
        body: Previously stored selection request.

    Returns:
        A separate request with the same candidates and output schema.
    """
    result = deepcopy(body)
    schema_name = result.get("response_format", {}).get("json_schema", {}).get("name")
    if schema_name not in {
        "parliament_claim_selection_v1",
        "parliament_source_group_selection_v2",
    }:
        raise ValueError("selection retry requires the selection schema")
    data = json.loads(result["messages"][-1]["content"])
    if data.get("task") != "select grounded claims":
        raise ValueError("selection retry requires a selection task")
    if schema_name == "parliament_source_group_selection_v2":
        if GROUP_SELECTION_UNIQUENESS not in data["rules"]:
            data["rules"] += GROUP_SELECTION_UNIQUENESS
            result["messages"][-1]["content"] = canonical(data).decode()
        return result
    if SELECTION_INVARIANT not in data["rules"]:
        data["rules"] += SELECTION_INVARIANT
        result["messages"][-1]["content"] = canonical(data).decode()
    return result


def selection_batches(
    question: str,
    claims: list[dict[str, Any]],
    *,
    source_facets: dict[str, str] | None = None,
) -> list[list[dict[str, Any]]]:
    """Fit every candidate exactly once within the model's request allowance."""
    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for claim in claims:
        candidate = current + [claim]
        try:
            selection_request(question, candidate, source_facets=source_facets)
        except ValueError:
            if not current:
                raise
            batches.append(current)
            current = [claim]
        else:
            current = candidate
    if current:
        batches.append(current)
    return batches


def materialize_selection(
    output: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Return unchanged validated input claims for selected IDs only."""
    aliases = context["selectionClaims"]
    if context.get("output_contract") == SOURCE_GROUP_SELECTION_CONTRACT:
        host_aliases = context["hostAliases"]
        if not isinstance(output, dict) or set(output) != {"hostChoices", "extra"}:
            raise ValueError("invalid source coverage selection output")
        choices, extra = output["hostChoices"], output["extra"]
        if not isinstance(choices, dict) or set(choices) != set(host_aliases):
            raise ValueError("invalid source coverage choices")
        if not isinstance(extra, list) or len(extra) > 4 - len(host_aliases):
            raise ValueError("invalid source coverage extras")
        if any(
            choices[group] not in allowed for group, allowed in host_aliases.items()
        ):
            raise ValueError("invalid source coverage claim ID")
        selected = [*choices.values(), *extra]
    else:
        if not isinstance(output, dict) or set(output) != {"selected", "insufficient"}:
            raise ValueError("invalid selection output")
        selected = output["selected"]
        if type(output["insufficient"]) is not bool or output["insufficient"] != (
            not selected
        ):
            raise ValueError("invalid selected claim IDs")
    if (
        not isinstance(selected, list)
        or len(selected) > 4
        or any(not isinstance(item, str) for item in selected)
        or len(set(selected)) != len(selected)
        or any(item not in aliases for item in selected)
    ):
        raise ValueError("invalid selected claim IDs")
    claims = [aliases[item] for item in selected]
    required_hosts = context.get("requiredHosts", [])
    selected_hosts = {
        urlparse(claim.get("evidence", {}).get("sourceUrl", "")).hostname
        for claim in claims
    }
    if required_hosts and not set(required_hosts) <= selected_hosts:
        raise ValueError("selected claims lack source coverage")
    required_facets = context.get("requiredFacets", [])
    source_facets = context.get("sourceFacets", {})
    selected_facets = {
        source_facets.get(claim["evidence"]["sourceUrl"]) for claim in claims
    }
    if required_facets and not set(required_facets) <= selected_facets:
        raise ValueError("selected claims lack source coverage")
    if any(
        not isinstance(claim.get("text"), str)
        or not isinstance(claim.get("evidence"), dict)
        for claim in claims
    ):
        raise ValueError("invalid pinned claim")
    return {
        "answer": "\n".join(dict.fromkeys(claim["text"] for claim in claims)),
        "claims": claims,
        "insufficient": not claims,
        "private": True,
        "reviewRequired": True,
    }
