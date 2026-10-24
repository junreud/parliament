"""Ask the model for bill-to-policy links missed by per-passage extraction."""

from typing import Any

from parliament_worker.graphrag.index import source_dependency
from parliament_worker.graphrag.inputs import fingerprint
from parliament_worker.graphrag.prompts import PROMPT_VERSION, request
from parliament_worker.graphrag.source_forms import source_form
from parliament_worker.graphrag.store import GraphStore

POLICY_CONTRACT = "official-bill-policy-relation-v1"
ACTIVE_STATES = frozenset({"planned", "deferred", "submitting", "polling"})


def _candidate(source: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Bind one typed bill record and an explicitly named issue policy."""
    payload = source["payload"]
    document = payload["document"]
    entities = {item["id"]: item for item in payload["entities"]}
    bill = entities.get(payload.get("documentBillId"))
    policy = entities.get(payload.get("issuePolicyId"))
    number = document.get("recordKey")
    if (
        document.get("sourceKey") != "lawmaking-bill-detail"
        or bill is None
        or policy is None
        or bill["kind"] != "bill"
        or policy["kind"] != "policy"
        or not any(
            identifier == {"namespace": "ASSEMBLY_BILL_NUMBER", "value": number}
            for identifier in bill.get("identifiers", [])
        )
    ):
        return None
    unit = next(
        (
            unit
            for unit in payload["units"]
            if source_form(unit["text"], policy["name"])
        ),
        None,
    )
    return (
        ({"billId": bill["id"], "policyId": policy["id"], "billNumber": number}, unit)
        if unit
        else None
    )


def _request(
    candidate: dict[str, Any], policy_name: str, unit: dict[str, Any]
) -> dict[str, Any]:
    """Request a binary relation judgment over a fixed official bill passage."""
    body = request(
        "verify bill policy relation",
        {
            "recordBillNumber": candidate["billNumber"],
            "policyName": policy_name,
            "source": {"passage": unit["text"]},
            "rules": (
                "Return supported=true only if this official bill record's supplied "
                "passage proposes or regulates the named policy. The record number "
                "identifies the bill; the policy name must appear in the passage. "
                "A passing mention, different proposal, or unknown connection is false. "
                "Do not infer policy outcomes, enactment, or individual credit."
            ),
        },
        output_tokens=128,
    )
    body["response_format"] = {
        "type": "json_schema",
        "json_schema": {
            "name": "bill_policy_relation",
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


def validate_policy_link(
    output: dict[str, Any], context: dict[str, Any], source: dict[str, Any]
) -> dict[str, Any]:
    """Materialize only a model-supported, source-bound private candidate."""
    if set(output) != {"supported"} or type(output["supported"]) is not bool:
        raise ValueError("invalid bill policy response")
    if context.get("sources") != [source_dependency(source)]:
        raise ValueError("bill policy source dependency mismatch")
    selected = _candidate(source)
    if (
        selected is None
        or context.get("candidate") != selected[0]
        or context.get("unit") != selected[1]
    ):
        raise ValueError("bill policy source candidate mismatch")
    candidate, unit = selected
    entities = {item["id"]: item for item in source["payload"]["entities"]}
    nodes = [
        {**entities[identifier], "identityStatus": "source_bound"}
        for identifier in (candidate["billId"], candidate["policyId"])
    ]
    edges = []
    if output["supported"]:
        edge = {
            "source": candidate["billId"],
            "target": candidate["policyId"],
            "type": "concerns",
            "evidence": [unit],
            "decision": "pending",
            "endpointSupported": True,
            "relationCueSupported": True,
            "documentIdentitySupported": True,
        }
        edges.append({"id": "edge_" + fingerprint(edge), **edge})
    return {"nodes": nodes, "edges": edges, "public": False}


def plan_policy_links(store: GraphStore, model_signature: str, capacity: int) -> int:
    """Queue one fixed-source model check for each missing logical pair."""
    jobs = store.jobs()
    room = capacity - sum(job["state"] in ACTIVE_STATES for job in jobs)
    if room <= 0:
        return 0
    known = {(job["kind"], job["key"]) for job in jobs}
    existing = {
        (edge["source"], edge["target"])
        for artifact in store.artifacts("graph")
        for edge in artifact["payload"].get("edges", [])
        if edge["type"] == "concerns"
    }
    planned = []
    for source in store.sources():
        selected = _candidate(source)
        if selected is None:
            continue
        candidate, unit = selected
        pair = (candidate["billId"], candidate["policyId"])
        if pair in existing:
            continue
        dependency = source_dependency(source)
        key = fingerprint(
            [
                dependency,
                candidate,
                unit["id"],
                model_signature,
                PROMPT_VERSION,
                POLICY_CONTRACT,
            ]
        )
        if ("extract", key) in known:
            continue
        policy = next(
            item
            for item in source["payload"]["entities"]
            if item["id"] == candidate["policyId"]
        )
        planned.append(
            {
                "kind": "extract",
                "key": key,
                "request": _request(candidate, policy["name"], unit),
                "context": {
                    "relation_task": "bill_policy",
                    "output_contract": POLICY_CONTRACT,
                    "sources": [dependency],
                    "candidate": candidate,
                    "unit": unit,
                    "artifact_key": f"{source['scope']}:policy:{candidate['policyId']}",
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
