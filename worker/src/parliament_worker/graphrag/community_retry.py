"""Tighter requests for repeatedly invalid community generations."""

import json
from copy import deepcopy
from typing import Any

from parliament_worker.graphrag.inputs import canonical
from parliament_worker.graphrag.output_contract import complete_community_contract

SHORT_QUOTE_COMMUNITY_CONTRACT = "parliament-community-short-quote-output-v1"
QUOTE_OPTIONS_COMMUNITY_CONTRACT = "parliament-community-quote-options-output-v1"


def short_quote_community_contract(body: dict[str, Any]) -> dict[str, Any]:
    """Retry a length-limited community with short, exact source excerpts.

    Args:
        body: Persisted strict community request; this object stays unchanged.

    Returns:
        A separate strict request. The ordinary local proof validator still
        rejects absent or ambiguous excerpts before any graph projection.
    """
    result = complete_community_contract(body)
    spec = result["response_format"]["json_schema"]
    if spec["name"] == "parliament_community_short_quote_v1":
        return result
    data = json.loads(result["messages"][-1]["content"])
    old_rule = "Copy the FULL supplied source passage as quote, including names and punctuation."
    if old_rule not in data["rules"]:
        raise ValueError("short quote retry needs the original full-quote rule")
    data["rules"] = data["rules"].replace(
        old_rule,
        "For each claim, copy a unique exact contiguous 2-120 character quote "
        "from its chosen source, including punctuation.",
    )
    result["messages"][-1]["content"] = canonical(data).decode()
    claim = spec["schema"]["properties"]["groups"]["items"]["properties"]["claims"][
        "items"
    ]["properties"]
    claim["quote"].pop("enum", None)
    claim["quote"]["minLength"] = 2
    claim["quote"]["maxLength"] = 120
    spec["name"] = "parliament_community_short_quote_v1"
    return result


def quote_options_community_contract(body: dict[str, Any]) -> dict[str, Any]:
    """Constrain a failed free-form quote to unique spans of the same source.

    Args:
        body: Persisted community request with fixed source aliases and text.

    Returns:
        A separate strict request. The local proof validator still checks the
        chosen unit, text, version, and position before projection.
    """
    original_name = body.get("response_format", {}).get("json_schema", {}).get("name")
    if original_name == "parliament_community_quote_options_v1":
        return deepcopy(body)
    result = complete_community_contract(body)
    data = json.loads(result["messages"][-1]["content"])
    options: dict[str, list[str]] = {}
    for alias, source in data["sources"].items():
        if not isinstance(source, str) or len(source) < 2:
            raise ValueError("quote options require a source passage")
        width = min(88, len(source))
        starts = (0, max(0, (len(source) - width) // 2), len(source) - width)
        choices = []
        for start in starts:
            quote = source[start : start + width]
            if source.count(quote) == 1 and quote not in choices:
                choices.append(quote)
        if not choices:
            raise ValueError("quote options need a unique source span")
        options[alias] = choices
    if not options:
        raise ValueError("quote options need supplied sources")
    data["quote_options"] = options
    data["rules"] += (
        " For each claim choose quote verbatim from quote_options for its unit."
        " Do not invent or alter a quote."
    )
    result["messages"][-1]["content"] = canonical(data).decode()
    spec = result["response_format"]["json_schema"]
    quote_schema = spec["schema"]["properties"]["groups"]["items"]["properties"][
        "claims"
    ]["items"]["properties"]["quote"]
    quote_schema["enum"] = list(
        dict.fromkeys(quote for choices in options.values() for quote in choices)
    )
    quote_schema["minLength"] = 2
    quote_schema["maxLength"] = 120
    spec["name"] = "parliament_community_quote_options_v1"
    return result


def precise_community_contract(body: dict[str, Any]) -> dict[str, Any]:
    """Ask the model to verify member coverage and literal source quotes.

    Args:
        body: A prior community request with its original source units.

    Returns:
        A new strict request that keeps the supplied evidence and schema.
    """
    result = deepcopy(body)
    spec = result.get("response_format", {}).get("json_schema", {})
    if spec.get("name") == "parliament_community_precise_v4":
        return result
    result = complete_community_contract(result)
    data = json.loads(result["messages"][-1]["content"])
    members = ", ".join(member["id"] for member in data["members"])
    data["rules"] = (
        "Partition supplied members into topical groups; every member ID must "
        f"occur exactly once: {members}. Use singleton groups for unrelated "
        "members. Each claim needs a supplied S unit and a unique exact "
        "contiguous substring of its source text as quote (2-60 characters). "
        'Never paraphrase a quote. If proof is uncertain, use claims=[] and summary="". '
        "No internal IDs like E1 in titles or claims; use member names. "
        "Describe scheduled actions as scheduled, never completed. "
        "Keep title and prose short. Return only the JSON object."
    )
    result["messages"][-1]["content"] = canonical(data).decode()
    result["response_format"]["json_schema"]["name"] = "parliament_community_precise_v4"
    return result


def assignment_community_contract(body: dict[str, Any]) -> dict[str, Any]:
    """Ask the provider for a complete partition when reports keep failing.

    Args:
        body: A prior community request containing members and source context.

    Returns:
        A strict member-to-cluster assignment request with no prose claims.
    """
    result = deepcopy(body)
    spec = result.get("response_format", {}).get("json_schema", {})
    if spec.get("name") == "parliament_community_assignment_v5":
        return result
    data = json.loads(result["messages"][-1]["content"])
    members = [member["id"] for member in data["members"]]
    if not members or len(set(members)) != len(members):
        raise ValueError("community assignment needs unique members")
    for member in data["members"]:
        if isinstance(member.get("summary"), str):
            member["summary"] = member["summary"][:120]
    data["sources"] = {alias: source[:120] for alias, source in data["sources"].items()}
    data["task"] = "assign every member to a topical community"
    data["rules"] = (
        "Use sources and relations only to decide grouping. Assign every listed "
        "member exactly one cluster number. Put unrelated members in different "
        "clusters. Do not write facts, summaries, quotes or claims."
    )
    data.pop("schema", None)
    data.pop("quote_options", None)
    result["messages"][-1]["content"] = canonical(data).decode()
    result["max_completion_tokens"] = 128
    result["response_format"] = {
        "type": "json_schema",
        "json_schema": {
            "name": "parliament_community_assignment_v5",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "assignments": {
                        "type": "object",
                        "properties": {
                            member: {
                                "type": "integer",
                                "enum": list(range(len(members))),
                            }
                            for member in members
                        },
                        "required": members,
                        "additionalProperties": False,
                    }
                },
                "required": ["assignments"],
                "additionalProperties": False,
            },
        },
    }
    return result


def materialize_partition(
    output: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Turn the provider's exact assignment into claim-free review groups.

    Args:
        output: Schema-constrained provider output.
        context: Fixed aliases and immutable source references for the job.

    Returns:
        Groups for the ordinary complete-membership validator.

    Raises:
        ValueError: If any member is missing, repeated or assigned out of range.
    """
    aliases = context["aliases"]
    assignments = output.get("assignments")
    if not isinstance(assignments, dict) or set(assignments) != set(aliases):
        raise ValueError("community assignment coverage incomplete")
    clusters: dict[int, list[str]] = {}
    for alias in aliases:
        cluster = assignments[alias]
        if type(cluster) is not int or cluster < 0 or cluster >= len(aliases):
            raise ValueError("invalid community cluster")
        clusters.setdefault(cluster, []).append(alias)
    groups = []
    for members in clusters.values():
        names = [
            str(aliases[member].get("name") or aliases[member].get("title") or member)
            for member in members
        ]
        groups.append(
            {
                "title": " · ".join(names)[:100],
                "members": members,
                "summary": "",
                "claims": [],
            }
        )
    return {"groups": groups}
