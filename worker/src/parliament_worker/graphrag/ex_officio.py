"""Build bounded ex officio chair candidates from two distinct official sources."""

import re
from typing import Any

from parliament_worker.graphrag.index import source_dependency
from parliament_worker.graphrag.inputs import fingerprint
from parliament_worker.graphrag.prompts import PROMPT_VERSION, request
from parliament_worker.graphrag.store import GraphStore

CONTRACT = "official-ex-officio-chair-two-source-v1"
PRESIDENT_SCOPE = "official-president-status:briefing-XvTXtZbh"
PRESIDENT_URL = "https://www.president.go.kr/briefings/XvTXtZbh"
RULES = {
    "official-exofficio-rule:neac-chair": (
        "https://www.neac.go.kr/agency/composition.do",
        "국민경제자문회의",
        "1790049",
    ),
    "official-exofficio-rule:pacst-chair": (
        "https://www.pacst.go.kr/jsp/pacstinfo/intro.jsp",
        "국가과학기술자문회의",
        "1074500",
    ),
    "official-exofficio-rule:puac-chair": (
        "https://www.puac.go.kr/lang/kr/view/intrcn/int_com_org.jsp",
        "민주평화통일자문회의",
        "1790238",
    ),
    "official-exofficio-rule:nsc-chair": (
        "https://law.go.kr/LSW/lsLinkCommonInfo.do?chrClsCd=010202&lsJoLnkSeq=1022982315",
        "국가안전보장회의",
        "1790237",
    ),
}
RULE_CUES = {
    "official-exofficio-rule:neac-chair": r"대통령\s*\(\s*의장\s*\)",
    "official-exofficio-rule:pacst-chair": r"대통령\s*\(\s*의장\s*\)",
    "official-exofficio-rule:puac-chair": r"\[\s*의장\s*:\s*대통령\s*\]",
    "official-exofficio-rule:nsc-chair": r"②\s*대통령은\s*회의의\s*의장이\s*된다\.",
}
ACTIVE_STATES = frozenset({"planned", "deferred", "submitting", "polling"})


def _single_unit(source: dict[str, Any], url: str) -> dict[str, Any] | None:
    """Accept only the curated single passage from the expected official URL."""
    payload = source["payload"]
    document = payload["document"]
    units = payload["units"]
    if (
        payload.get("public") is not False
        or payload.get("bodyCoverage") != "selected_evidence"
        or document.get("sourceUrl") != url
        or document.get("bodyStatus") != "available"
        or len(units) != 1
        or units[0].get("sourceUrl") != url
        or units[0].get("documentId") != document.get("id")
        or units[0].get("documentVersion") != document.get("version")
        or units[0].get("extractionVersion") != document.get("extractionVersion")
    ):
        return None
    return units[0]


def _candidate(
    president: dict[str, Any], rule: dict[str, Any]
) -> tuple[dict[str, str], dict[str, dict[str, Any]]] | None:
    """Match one president record and one explicitly named chair rule."""
    if president["scope"] != PRESIDENT_SCOPE or rule["scope"] not in RULES:
        return None
    rule_url, organization_name, organization_number = RULES[rule["scope"]]
    president_doc = president["payload"]["document"]
    rule_doc = rule["payload"]["document"]
    if (
        president_doc.get("sourceKey") != "official-president-status"
        or president_doc.get("recordKey") != "briefing-XvTXtZbh"
        or rule_doc.get("sourceKey") != "official-exofficio-rule"
        or rule_doc.get("recordKey") != rule["scope"].split(":", 1)[1]
        or organization_name not in rule_doc.get("title", "")
    ):
        return None
    president_unit = _single_unit(president, PRESIDENT_URL)
    rule_unit = _single_unit(rule, rule_url)
    if president_unit is None or rule_unit is None:
        return None
    people = [
        entity
        for entity in president["payload"]["entities"]
        if entity.get("kind") == "person"
        and any(
            item.get("namespace") == "KR_OFFICE_PROFILE_CANDIDATE"
            for item in entity.get("identifiers", [])
        )
    ]
    organizations = [
        entity
        for entity in rule["payload"]["entities"]
        if entity.get("kind") == "organization"
        and entity.get("name") == organization_name
        and any(
            item
            == {
                "namespace": "MOIS_GOVERNMENT_ORGANIZATION",
                "value": organization_number,
            }
            for item in entity.get("identifiers", [])
        )
    ]
    if len(people) != 1 or len(organizations) != 1:
        return None
    if not re.search(
        re.escape(people[0]["name"]) + r"\s*대통령", president_unit["text"]
    ):
        return None
    if not re.search(RULE_CUES[rule["scope"]], rule_unit["text"]):
        return None
    return (
        {"personId": people[0]["id"], "organizationId": organizations[0]["id"]},
        {"P": president_unit, "R": rule_unit},
    )


def _request(
    candidate: dict[str, str], units: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Constrain model output to one source-bound Boolean judgment."""
    body = request(
        "verify official ex officio chair relation",
        {
            "candidate": {**candidate, "relation": "holds_office", "role": "의장"},
            "source": {
                "president_status": units["P"]["text"],
                "chair_rule": units["R"]["text"],
            },
            "rules": (
                "Return supported=true only when the first official passage explicitly "
                "identifies the named person as president and the second official "
                "passage explicitly states that the president is this body's chair. "
                "Both passages are required. Do not infer an appointment date, "
                "individual action, vote, policy position, or any other identity."
            ),
        },
        output_tokens=128,
    )
    body["response_format"] = {
        "type": "json_schema",
        "json_schema": {
            "name": "ex_officio_chair",
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


def validate_ex_officio_link(
    output: dict[str, Any],
    context: dict[str, Any],
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    """Project a private chair edge only against both persisted source revisions."""
    if set(output) != {"supported"} or type(output["supported"]) is not bool:
        raise ValueError("invalid ex officio response")
    if (
        len(sources) != 2
        or context.get("sources") != [source_dependency(item) for item in sources]
        or context.get("output_contract") != CONTRACT
    ):
        raise ValueError("ex officio source dependency mismatch")
    selected = _candidate(*sources)
    if selected is None:
        raise ValueError("ex officio source candidate missing")
    candidate, units = selected
    if (
        context.get("candidate") != candidate
        or context.get("units") != units
        or context.get("personId") != candidate["personId"]
        or context.get("organizationId") != candidate["organizationId"]
    ):
        raise ValueError("ex officio source candidate mismatch")
    entities = {
        item["id"]: item for source in sources for item in source["payload"]["entities"]
    }
    nodes = [
        {**entities[identifier], "identityStatus": "source_bound"}
        for identifier in (candidate["personId"], candidate["organizationId"])
    ]
    edges = []
    if output["supported"]:
        edge = {
            "source": candidate["personId"],
            "target": candidate["organizationId"],
            "type": "holds_office",
            "role": "의장",
            "asOfSourcePublication": sources[0]["payload"]["document"].get(
                "publishedAt"
            ),
            "evidence": [units["P"], units["R"]],
            "decision": "pending",
            "endpointSupported": True,
            "relationCueSupported": True,
        }
        edges.append({"id": "edge_" + fingerprint(edge), **edge})
    return {"nodes": nodes, "edges": edges, "public": False}


def plan_ex_officio_links(
    store: GraphStore, model_signature: str, capacity: int
) -> int:
    """Queue one revision-specific decision for each supported official rule."""
    jobs = store.jobs()
    room = capacity - sum(job["state"] in ACTIVE_STATES for job in jobs)
    if room <= 0:
        return 0
    known = {(job["kind"], job["key"]) for job in jobs}
    sources = {item["scope"]: item for item in store.sources()}
    president = sources.get(PRESIDENT_SCOPE)
    if president is None:
        return 0
    planned = []
    for rule_scope in RULES:
        rule = sources.get(rule_scope)
        if rule is None:
            continue
        selected = _candidate(president, rule)
        if selected is None:
            continue
        candidate, units = selected
        dependencies = [source_dependency(item) for item in (president, rule)]
        key = fingerprint(
            [
                dependencies,
                candidate,
                [units["P"]["id"], units["R"]["id"]],
                model_signature,
                PROMPT_VERSION,
                CONTRACT,
            ]
        )
        if ("extract", key) in known:
            continue
        planned.append(
            {
                "kind": "extract",
                "key": key,
                "request": _request(candidate, units),
                "context": {
                    "relation_task": "ex_officio_chair",
                    "output_contract": CONTRACT,
                    "sources": dependencies,
                    "candidate": candidate,
                    "personId": candidate["personId"],
                    "organizationId": candidate["organizationId"],
                    "units": units,
                    "artifact_key": "exofficio_"
                    + fingerprint([PRESIDENT_SCOPE, rule_scope]),
                    "model_signature": model_signature,
                    "prompt_version": PROMPT_VERSION,
                },
            }
        )
        known.add(("extract", key))
        if len(planned) >= room:
            break
    if planned:
        store.enqueue_many(planned)
    return len(planned)
