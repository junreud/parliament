"""Strict, versioned model output shapes; facts still pass independent validation."""

import json
import re
from copy import deepcopy
from typing import Any

from parliament_worker.graphrag.inputs import canonical

OUTPUT_CONTRACT = "parliament-graph-output-v2"
COMPACT_CONTRACT = "parliament-graph-compact-output-v4"
DIRECTIONAL_CONTRACT = "parliament-graph-directional-output-v6"
COMPLETE_COMMUNITY_CONTRACT = "parliament-community-complete-output-v3"
PRECISE_COMMUNITY_CONTRACT = "parliament-community-precise-output-v4"
ASSIGNMENT_COMMUNITY_CONTRACT = "parliament-community-assignment-output-v5"
LEGACY_ANSWER_CONTRACT = "parliament-answer-selector-v2"
ANSWER_CONTRACT = "parliament-answer-claims-v3"


def _source_names(source: dict[str, str]) -> list[str]:
    """Offer bounded exact source spans instead of free-form entity names."""
    found: dict[str, None] = {}
    for passage in source.values():
        words = list(re.finditer(r"[가-힣A-Za-z0-9][가-힣A-Za-z0-9·-]{1,39}", passage))
        for match in words:
            found.setdefault(match.group(), None)
        for left, right in zip(words, words[1:]):
            if passage[left.end() : right.start()] == " ":
                phrase = passage[left.start() : right.end()]
                if len(phrase) <= 60:
                    found.setdefault(phrase, None)
    return list(found)[:128]


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _string(limit: int, *, choices: list[str] | None = None) -> dict[str, Any]:
    result = {"type": "string", "minLength": 1, "maxLength": limit}
    if choices:
        result["enum"] = choices
    return result


def _array(item: dict[str, Any], limit: int, minimum: int = 0) -> dict[str, Any]:
    return {"type": "array", "items": item, "minItems": minimum, "maxItems": limit}


def _proof(sources: dict[str, str]) -> dict[str, Any]:
    return {
        "unit": _string(32, choices=list(sources)),
        "quote": _string(850, choices=list(dict.fromkeys(sources.values()))),
    }


def _schema(data: dict[str, Any]) -> dict[str, Any] | None:
    task = data["task"]
    if task.startswith("answer"):
        claim = _object(
            {
                "text": _string(350),
                "proof": _string(32, choices=list(data["sources"])),
            }
        )
        return _object({"claims": _array(claim, 4)})
    if task.startswith("extract"):
        passages = tuple(data["source"].values())
        aliases = [
            item["id"]
            for item in data["known"]
            if any(item["name"] in passage for passage in passages)
            or (
                item["kind"] != "person"
                and any(
                    len(value) >= 4 and value in passage
                    for passage in passages
                    for value in item.get("externalIds", [])
                )
            )
        ] + ["N1", "N2", "N3", "N4"]
        proof = _proof(data["source"])
        entity = _object(
            {
                "id": _string(32, choices=["N1", "N2", "N3", "N4"]),
                "name": _string(100),
                "kind": _string(
                    32, choices=["person", "organization", "bill", "policy"]
                ),
                **proof,
            }
        )
        relation = _object(
            {
                "s": _string(32, choices=aliases),
                "t": _string(32, choices=aliases),
                "type": _string(64, choices=data["types"]),
                **proof,
            }
        )
        return _object(
            {"entities": _array(entity, 4), "relations": _array(relation, 6)}
        )
    if task.startswith("assign"):
        aliases = [item["id"] for item in data["members"]]
        claim = _object({"text": _string(250), **_proof(data["sources"])})
        group = _object(
            {
                "title": _string(100),
                "members": _array(_string(32, choices=aliases), len(aliases), 1),
                "summary": {"type": "string", "maxLength": 500},
                "claims": _array(claim, 2 if data["sources"] else 0),
            }
        )
        return _object({"groups": _array(group, 3, 1)})
    return None


def enforce_output_contract(body: dict[str, Any]) -> dict[str, Any]:
    """Build a new request without changing the persisted original body.

    Quotes are full supplied passages, avoiding paraphrase and ambiguous short
    substrings. Unit/quote matching, endpoint identity and roles are still checked
    by the local validators after decoding.

    Args:
        body: Original request body; callers persist the returned version separately.

    Returns:
        A copied request with a strict schema for extraction/community tasks.
    """
    result = deepcopy(body)
    data = json.loads(result["messages"][-1]["content"])
    schema = _schema(data)
    if schema is None:
        return result
    data.pop("schema", None)
    if data["task"].startswith("answer"):
        data["rules"] += (
            " Respond with one compact JSON object. Every claim must include its"
            " supplied proof ID. The local validator attaches the exact fixed"
            " source text; do not repeat or rewrite that text."
            " Return claims=[] when no supplied source supports a claim."
            " The local validator derives whether evidence is insufficient"
            " from the validated claims. Do not output an insufficient field."
        )
    else:
        data["rules"] += (
            " Respond with a single compact JSON line. No indentation, newlines, or extra whitespace."
            " Put unit and quote directly on EACH entity/relation/claim, not in an evidence object."
            " Copy the FULL supplied source passage as quote, including names and punctuation."
            " lead_sponsor/co_sponsor: person -> bill; holds_office: person -> organization;"
            " incorporated_into_alternative: bill -> bill. Never use these roles for other kinds."
            " If no supplied evidence supports a relation, omit it."
            ' Community claims=[] requires summary="".'
        )
    result["messages"][-1]["content"] = canonical(data).decode()
    result["messages"][0][
        "content"
    ] += " Respond with a single compact JSON line. No indentation, newlines, or extra whitespace."
    result["response_format"] = {
        "type": "json_schema",
        "json_schema": {
            "name": (
                "parliament_answer_claims_v3"
                if data["task"].startswith("answer")
                else "parliament_graph"
            ),
            "strict": True,
            "schema": schema,
        },
    }
    return result


def answer_selector_contract(body: dict[str, Any]) -> dict[str, Any]:
    """Upgrade an older answer request to claims-only output.

    Args:
        body: Original answer request or a prior output-contract attempt.

    Returns:
        A strict source-selector request with the same supplied evidence.
    """
    if (
        body.get("response_format", {}).get("json_schema", {}).get("name")
        == "parliament_answer_claims_v3"
    ):
        return deepcopy(body)
    result = deepcopy(body)
    data = json.loads(result["messages"][-1]["content"])
    if not data.get("task", "").startswith("answer"):
        raise ValueError("answer selector requires an answer task")
    for obsolete in (
        "If unanswerable return empty claims and insufficient=true.",
        "If the supplied records do not answer the question, return claims=[] and insufficient=true.",
        "Set insufficient=true only when claims=[]. If any supported claim is returned, set insufficient=false, even if the records answer only part of the question. Never return claims together with insufficient=true.",
    ):
        data["rules"] = data["rules"].replace(obsolete, "")
    result["messages"][-1]["content"] = canonical(data).decode()
    return enforce_output_contract(result)


def materialize_answer(
    output: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Attach exact selected source text before the existing proof check.

    Args:
        output: Strict answer-selector model response.
        context: Immutable proof units pinned to the original question.

    Returns:
        Legacy answer shape with exact unit and quote fields.
    """
    if not isinstance(output, dict) or set(output) not in (
        {"claims"},
        {"claims", "insufficient"},
    ):
        raise ValueError("invalid answer selector shape")
    if not isinstance(output["claims"], list):
        raise ValueError("invalid answer selector claims")
    if "insufficient" in output and type(output["insufficient"]) is not bool:
        raise ValueError("invalid answer selector state")
    claims = []
    for claim in output["claims"]:
        if not isinstance(claim, dict) or set(claim) != {"text", "proof"}:
            raise ValueError("invalid answer selector claim")
        unit = claim["proof"]
        evidence = context["units"].get(unit)
        if (
            not isinstance(unit, str)
            or not isinstance(evidence, dict)
            or not isinstance(evidence.get("text"), str)
        ):
            raise ValueError("unknown answer proof")
        claims.append({"text": claim["text"], "unit": unit, "quote": evidence["text"]})
    return {
        "claims": claims,
        "insufficient": output.get("insufficient", not claims),
    }


def compact_extraction_contract(body: dict[str, Any]) -> dict[str, Any]:
    """Constrain model links to distinct aliases and transmit evidence by unit ID.

    The trusted local extractor restores the exact unit text before the existing
    identity, role, and evidence validators run. This avoids repeating a long
    passage once for every candidate relation.

    Args:
        body: Persisted earlier extraction request.

    Returns:
        A separate compact request, leaving the earlier attempt untouched.
    """
    result = deepcopy(body)
    if (
        result.get("response_format", {}).get("json_schema", {}).get("name")
        == "parliament_graph_compact_v4"
    ):
        return result
    data = json.loads(result["messages"][-1]["content"])
    if not data.get("task", "").startswith("extract"):
        raise ValueError("compact contract requires extraction task")
    aliases = [
        item["id"]
        for item in data["known"]
        if item["id"] == data.get("recordBill", {}).get("alias")
        or any(item["name"] in passage for passage in data["source"].values())
        or (
            item["kind"] != "person"
            and any(
                len(value) >= 4 and value in passage
                for passage in data["source"].values()
                for value in item.get("externalIds", [])
            )
        )
    ]
    pairs = [
        f"{left}>{right}" for left in aliases for right in aliases if left != right
    ]
    unit = _string(32, choices=list(data["source"]))
    names = _source_names(data["source"])
    entity = _object(
        {
            "id": _string(32, choices=["N1", "N2", "N3", "N4"]),
            "name": _string(100, choices=names),
            "kind": _string(32, choices=["person", "organization", "bill", "policy"]),
            "unit": unit,
        }
    )
    relation = _object(
        {
            "pair": _string(64, choices=pairs),
            "type": _string(64, choices=data["types"]),
            "unit": unit,
        }
    )
    data.pop("schema", None)
    data["rules"] = (
        "Relations use only source-bound known aliases; new N entities are separate candidates. "
        "A relation pair is subject>target with TWO DISTINCT entities. "
        "Each relation needs explicit support in its selected unit; omit uncertain links. "
        "New entity names must be exact offered source spans; do not alter spelling. "
        "At most 4 new entities and 6 relations. Return empty lists when unsupported. "
        "Do not repeat source text or invent roles, identity, votes, or policy credit. "
        "Respond as one compact JSON object with no extra whitespace."
    )
    result["messages"][-1]["content"] = canonical(data).decode()
    result["messages"][0]["content"] = result["messages"][0]["content"].replace(
        "with exact source quotes.", "with source unit IDs."
    )
    result["response_format"] = {
        "type": "json_schema",
        "json_schema": {
            "name": "parliament_graph_compact_v4",
            "strict": True,
            "schema": _object(
                {
                    "entities": _array(entity, 4 if names else 0),
                    "relations": _array(relation, 6 if pairs else 0),
                }
            ),
        },
    }
    return result


def directional_extraction_contract(body: dict[str, Any]) -> dict[str, Any]:
    """Restrict role directions while retaining the compact evidence contract.

    Args:
        body: Earlier extraction request or compact retry request.

    Returns:
        A new request with relation type and endpoint pair encoded together.
    """
    # Prompts imports this module, so load the shared endpoint rule at call time.
    from parliament_worker.graphrag.prompts import valid_relation_endpoints

    result = compact_extraction_contract(body)
    data = json.loads(result["messages"][-1]["content"])
    known = {
        item["id"]: item
        for item in data["known"]
        if item["id"] == data.get("recordBill", {}).get("alias")
        or any(item["name"] in passage for passage in data["source"].values())
        or (
            item["kind"] != "person"
            and any(
                len(value) >= 4 and value in passage
                for passage in data["source"].values()
                for value in item.get("externalIds", [])
            )
        )
    }
    claims = []
    for role in data["types"]:
        for left in known.values():
            for right in known.values():
                if left["id"] == right["id"]:
                    continue
                if not valid_relation_endpoints(role, left["kind"], right["kind"]):
                    continue
                claims.append(f'{role}:{left["id"]}>{right["id"]}')
    schema = result["response_format"]["json_schema"]["schema"]
    relations = schema["properties"]["relations"]
    relations["maxItems"] = 6 if claims else 0
    relations["items"] = _object(
        {
            "claim": _string(96, choices=claims),
            "unit": _string(32, choices=list(data["source"])),
        }
    )
    result["response_format"]["json_schema"]["name"] = "parliament_graph_directional_v6"
    data["rules"] += (
        " Each relation claim is role:subject>target. The role and direction must"
        " match one offered claim exactly; never reverse an office or sponsor role."
    )
    result["messages"][-1]["content"] = canonical(data).decode()
    return result


def materialize_compact_extraction(
    output: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Attach exact immutable evidence text to compact model selections.

    Args:
        output: Strict compact model response.
        context: Pinned source units and source-bound aliases.

    Returns:
        Legacy extraction shape for independent semantic validation.
    """
    if not isinstance(output, dict) or set(output) != {"entities", "relations"}:
        raise ValueError("invalid compact extraction shape")
    if not isinstance(output["entities"], list) or not isinstance(
        output["relations"], list
    ):
        raise ValueError("invalid compact extraction lists")
    aliases = set(context["aliases"])

    def unique_span(text: str, name: str) -> str:
        if name not in text:
            raise ValueError("new name lacks exact evidence")
        position = text.find(name)
        while position >= 0:
            for width in range(len(text) + 1):
                left = max(0, position - width)
                right = min(len(text), position + len(name) + width)
                quote = text[left:right]
                if (
                    2 <= len(quote) <= 850
                    and quote.count(name) == 1
                    and text.count(quote) == 1
                ):
                    return quote
                if left == 0 and right == len(text):
                    break
            position = text.find(name, position + 1)
        raise ValueError("new name lacks unique evidence")

    def with_proof(item: dict[str, Any], *, name: str | None = None) -> dict[str, Any]:
        unit = context["units"].get(item.get("unit"))
        if not unit or not isinstance(unit.get("text"), str):
            raise ValueError("invalid compact evidence unit")
        quote = unit["text"] if name is None else unique_span(unit["text"], name)
        return {**item, "quote": quote}

    entities = []
    for item in output["entities"]:
        if not isinstance(item, dict) or set(item) != {"id", "name", "kind", "unit"}:
            raise ValueError("invalid compact entity")
        if not isinstance(item["name"], str):
            raise ValueError("invalid compact entity name")
        entities.append(with_proof(item, name=item["name"]))
    relations = []
    for item in output["relations"]:
        if not isinstance(item, dict):
            raise ValueError("invalid compact relation")
        if set(item) == {"claim", "unit"}:
            claim = item["claim"]
            if not isinstance(claim, str) or claim.count(":") != 1:
                raise ValueError("invalid compact claim")
            role, pair = claim.split(":")
        elif set(item) == {"pair", "type", "unit"}:
            role, pair = item["type"], item["pair"]
        else:
            raise ValueError("invalid compact relation")
        if not isinstance(pair, str) or pair.count(">") != 1:
            raise ValueError("invalid compact pair")
        subject, target = pair.split(">")
        if subject == target or subject not in aliases or target not in aliases:
            raise ValueError("invalid compact pair")
        relations.append(
            with_proof({"s": subject, "t": target, "type": role, "unit": item["unit"]})
        )
    return {"entities": entities, "relations": relations}


def complete_community_contract(body: dict[str, Any]) -> dict[str, Any]:
    """Let every supplied member occupy a separate model-assigned group.

    Args:
        body: Earlier community request retained as immutable evidence.

    Returns:
        A new strict request that requires the model to account for every ID.
    """
    result = deepcopy(body)
    spec = result.get("response_format", {}).get("json_schema", {})
    if spec.get("name") == "parliament_community_complete_v3":
        return result
    data = json.loads(result["messages"][-1]["content"])
    if not data.get("task", "").startswith("assign"):
        raise ValueError("complete community contract requires assignment task")
    members = [member["id"] for member in data["members"]]
    if not members:
        raise ValueError("community task has no members")
    data["rules"] += (
        " Every supplied member ID must occur in exactly one group."
        " If members are unrelated, use singleton groups. Required IDs: "
        + ", ".join(members)
        + "."
    )
    result["messages"][-1]["content"] = canonical(data).decode()
    schema = result["response_format"]["json_schema"]["schema"]
    schema["properties"]["groups"]["maxItems"] = len(members)
    result["response_format"]["json_schema"][
        "name"
    ] = "parliament_community_complete_v3"
    return result
