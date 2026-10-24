"""Request source-bound model checks for cross-page bill alternative lineage."""

import re
from typing import Any

from parliament_worker.graphrag.index import source_dependency
from parliament_worker.graphrag.inputs import fingerprint
from parliament_worker.graphrag.prompts import PROMPT_VERSION, request
from parliament_worker.graphrag.store import GraphStore

LINEAGE_CONTRACT = "bill-alternative-cross-page-v1"
ACTIVE_STATES = frozenset({"planned", "deferred", "submitting", "polling"})


def _bill_number(entity: dict[str, Any]) -> str | None:
    """Use only an explicit, source-namespaced assembly bill number."""
    for identifier in entity.get("identifiers", []):
        if identifier.get("namespace") == "ASSEMBLY_BILL_NUMBER":
            value = identifier.get("value")
            if isinstance(value, str) and re.fullmatch(r"\d{7}", value):
                return value
    return None


def _parts(
    units: list[dict[str, Any]], original: dict[str, Any], alternative: dict[str, Any]
) -> dict[str, dict[str, Any]] | None:
    """Choose immutable units with title, committee decision, and bill row."""
    original_number = _bill_number(original)
    if original_number is None or _bill_number(alternative) is None:
        return None
    header = next(
        (
            unit
            for unit in units
            if alternative["name"] in unit["text"] and "대안의 제안경위" in unit["text"]
        ),
        None,
    )
    decision = next(
        (
            unit
            for unit in units
            if "통합" in unit["text"]
            and "대안" in unit["text"]
            and re.search(r"위\s*\d+\s*건", unit["text"])
        ),
        None,
    )
    row = next(
        (
            unit
            for unit in units
            if re.search(r"(?<!\d)" + original_number + r"(?!\d)", unit["text"])
        ),
        None,
    )
    return (
        {"header": header, "decision": decision, "row": row}
        if header and decision and row
        else None
    )


def _request(
    original: dict[str, Any],
    alternative: dict[str, Any],
    parts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Ask the remote model for the relation decision only."""
    body = request(
        "verify incorporated bill lineage",
        {
            "candidate": {
                "originalNumber": _bill_number(original),
                "alternativeNumber": _bill_number(alternative),
                "alternativeTitle": alternative["name"],
            },
            "source": {key: unit["text"] for key, unit in parts.items()},
            "rules": (
                "Return supported=true only if the named original bill is in the "
                "listed bills that the committee merged into this alternative. "
                "Use the header, the exact original bill number, and the committee "
                "decision together. A shared title or co-occurrence is insufficient. "
                "Do not infer clause contributions, authorship credit, or enactment."
            ),
        },
        output_tokens=128,
    )
    body["response_format"] = {
        "type": "json_schema",
        "json_schema": {
            "name": "bill_lineage",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {"supported": {"type": "boolean"}},
                "required": ["supported"],
                "additionalProperties": False,
            },
        },
    }
    return body


def validate_lineage(
    output: dict[str, Any], context: dict[str, Any], source: dict[str, Any]
) -> dict[str, Any]:
    """Materialize a model-confirmed link only from the pinned original units.

    Args:
        output: Strict boolean decision returned by the remote model.
        context: Durable request and its exact source-unit references.
        source: Current immutable source revision matching the dependency.

    Returns:
        A private graph whose political relationship remains pending review.

    Raises:
        ValueError: The response, candidate, dependency, or proof was changed.
    """
    if set(output) != {"supported"} or type(output["supported"]) is not bool:
        raise ValueError("invalid bill lineage response")
    if context.get("sources") != [source_dependency(source)]:
        raise ValueError("bill lineage source proof dependency mismatch")
    candidate = context.get("candidate")
    if candidate not in source["payload"].get("relationCandidates", []):
        raise ValueError("bill lineage source proof candidate mismatch")
    entities = {item["id"]: item for item in source["payload"]["entities"]}
    original = entities.get(candidate["subjectId"])
    alternative = entities.get(candidate["objectId"])
    if (
        original is None
        or alternative is None
        or original["kind"] != "bill"
        or alternative["kind"] != "bill"
        or candidate["type"] != "incorporated_into_alternative"
    ):
        raise ValueError("bill lineage source proof endpoints mismatch")
    expected = _parts(source["payload"]["units"], original, alternative)
    if expected is None or context.get("units") != expected:
        raise ValueError("bill lineage source proof units mismatch")
    nodes = [
        {**item, "identityStatus": "source_bound"} for item in (original, alternative)
    ]
    edges = []
    if output["supported"]:
        evidence = list({unit["id"]: unit for unit in expected.values()}.values())
        edge = {
            "source": original["id"],
            "target": alternative["id"],
            "type": "incorporated_into_alternative",
            "evidence": evidence,
            "decision": "pending",
            "endpointSupported": True,
            "relationCueSupported": True,
        }
        edges.append({"id": "edge_" + fingerprint(edge), **edge})
    return {"nodes": nodes, "edges": edges, "public": False}


def plan_lineage_repairs(store: GraphStore, model_signature: str, capacity: int) -> int:
    """Queue distinct remote checks for pending, cross-page bill candidates.

    Args:
        store: Private graph state and immutable source revisions.
        model_signature: Pinned actual model and revision.
        capacity: Shared planned and in-flight request ceiling.

    Returns:
        Number of newly queued source-bound model requests.
    """
    jobs = store.jobs()
    room = capacity - sum(job["state"] in ACTIVE_STATES for job in jobs)
    if room <= 0:
        return 0
    known = {(job["kind"], job["key"]) for job in jobs}
    existing = {
        (edge["source"], edge["target"], edge["type"])
        for artifact in store.artifacts("graph")
        for edge in artifact["payload"].get("edges", [])
    }
    planned = []
    for source in store.sources():
        candidates = source["payload"].get("relationCandidates", [])
        if not candidates:
            continue
        entities = {item["id"]: item for item in source["payload"]["entities"]}
        dependency = source_dependency(source)
        for candidate in candidates:
            original = entities.get(candidate["subjectId"])
            alternative = entities.get(candidate["objectId"])
            pair = (
                candidate["subjectId"],
                candidate["objectId"],
                "incorporated_into_alternative",
            )
            if (
                candidate["type"] != pair[2]
                or not original
                or not alternative
                or original["kind"] != "bill"
                or alternative["kind"] != "bill"
                or pair in existing
            ):
                continue
            parts = _parts(source["payload"]["units"], original, alternative)
            if parts is None:
                continue
            key = fingerprint(
                [dependency, pair, model_signature, PROMPT_VERSION, LINEAGE_CONTRACT]
            )
            if ("extract", key) in known:
                continue
            planned.append(
                {
                    "kind": "extract",
                    "key": key,
                    "request": _request(original, alternative, parts),
                    "context": {
                        "relation_task": "bill_lineage",
                        "output_contract": LINEAGE_CONTRACT,
                        "sources": [dependency],
                        "units": parts,
                        "candidate": candidate,
                        "artifact_key": (
                            f"{source['scope']}:lineage:{original['id']}:"
                            f"{alternative['id']}"
                        ),
                        "model_signature": model_signature,
                        "prompt_version": PROMPT_VERSION,
                    },
                }
            )
            known.add(("extract", key))
            if len(planned) >= room:
                store.enqueue_many(planned)
                return len(planned)
    if planned:
        store.enqueue_many(planned)
    return len(planned)
