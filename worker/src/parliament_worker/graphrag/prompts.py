"""Bounded remote semantic tasks with compact aliases and exact proof spans."""

import re
from collections import Counter
from typing import Any

from parliament_worker.graphrag.claim_quality import claim_quality_flags
from parliament_worker.graphrag.community_retry import (
    QUOTE_OPTIONS_COMMUNITY_CONTRACT,
    SHORT_QUOTE_COMMUNITY_CONTRACT,
)
from parliament_worker.graphrag.inputs import fingerprint
from parliament_worker.graphrag.output_contract import (
    ASSIGNMENT_COMMUNITY_CONTRACT,
    COMPLETE_COMMUNITY_CONTRACT,
    OUTPUT_CONTRACT,
    PRECISE_COMMUNITY_CONTRACT,
)
from parliament_worker.graphrag.prompt_request import request
from parliament_worker.graphrag.relation_types import (
    EXTRACTABLE_KINDS,
    EXTRACTABLE_RELATION_TYPES,
    RELATION_ENDPOINTS,
    RELATION_TYPES,
    prune_invalid_graph_edges,
    valid_relation_endpoints,
)
from parliament_worker.graphrag.source_forms import (
    same_spelling_ignoring_space,
    source_form,
)
from parliament_worker.graphrag.system_prompt import SYSTEM

PROMPT_VERSION = "parliament-graphrag-v3"
GROUP_ID_VERSION = "report-key-scoped-v1"


def extraction(
    source: dict[str, Any], unit: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Ask the model for new entities and evidenced typed relationships."""
    entities = source["payload"]["entities"]
    text = unit["text"]
    document_bill_id = source["payload"].get("documentBillId")
    issue_policy_id = source["payload"].get("issuePolicyId")
    policy_in_unit = any(
        entity["id"] == issue_policy_id
        and source_form(text, entity["name"]) is not None
        for entity in entities
    )
    name_counts = Counter(entity["name"] for entity in entities)
    offered = []
    for entity in entities:
        identifiers = [
            identifier["value"] for identifier in entity.get("identifiers", [])
        ]
        identified = any(
            len(value) >= 4
            and (
                re.search(r"(?<!\d)" + re.escape(value) + r"(?!\d)", text)
                if value.isdigit()
                else value in text
            )
            for value in identifiers
        )
        if (
            identified
            or (policy_in_unit and entity["id"] == document_bill_id)
            or (
                name_counts[entity["name"]] == 1
                and source_form(text, entity["name"]) is not None
            )
        ):
            offered.append(entity)
    aliases = {f"E{i + 1}": entity for i, entity in enumerate(offered)}
    compact = [
        {
            "id": alias,
            "name": entity["name"],
            "kind": entity["kind"],
            "externalIds": [
                identifier["value"] for identifier in entity.get("identifiers", [])
            ],
        }
        for alias, entity in aliases.items()
    ]
    data = {
        "known": compact,
        "source": {"U1": unit["text"]},
        "types": sorted(EXTRACTABLE_RELATION_TYPES),
        "schema": {
            "entities": [
                {
                    "id": "N1",
                    "name": "new name",
                    "kind": "person|organization|bill|policy",
                    "unit": "U1",
                    "quote": "exact substring",
                }
            ],
            "relations": [
                {
                    "s": "E1 or N1",
                    "t": "E2 or N1",
                    "type": "listed type",
                    "unit": "U1",
                    "quote": "exact substring supporting role",
                }
            ],
        },
        "rules": "Known aliases are source-bound, not name merges. Return at most 4 new entities and 6 relations. Empty lists when unsupported. New names must appear in quote. Each relation quote MUST include BOTH endpoint names or supplied externalIds. Copy the entire exact source passage when necessary; never remove an endpoint from its quote.",
    }
    context = {
        "aliases": aliases,
        "units": {"U1": unit},
        "output_contract": OUTPUT_CONTRACT,
    }
    record_bill_alias = next(
        (
            alias
            for alias, entity in aliases.items()
            if entity["id"] == document_bill_id
        ),
        None,
    )
    if (
        document_bill_id
        and source["payload"]["document"]["sourceKey"] == "lawmaking-bill-detail"
    ):
        context.update(
            documentBillId=document_bill_id,
            documentRecordKey=source["payload"]["document"]["recordKey"],
            documentSourceKey="lawmaking-bill-detail",
        )
        data["rules"] += (
            " In this official bill-detail record, lead_sponsor and co_sponsor"
            " can target only its numbered recordBill. If recordBill is not"
            " offered for this passage, omit those relations. Never create a"
            " second bill entity for the same record number."
        )
    if record_bill_alias:
        data["recordBill"] = {
            "alias": record_bill_alias,
            "number": source["payload"]["document"]["recordKey"],
        }
    if policy_in_unit and record_bill_alias:
        data["rules"] += (
            " Exception for concerns from recordBill to a policy explicitly named in"
            " this passage: the bill identity is anchored by this official bill"
            " record number, even when its title is in another passage."
            " Do not infer policy effects or relations from issue grouping alone."
        )
    context["allowedLineagePairs"] = [
        [candidate["subjectId"], candidate["objectId"]]
        for candidate in source["payload"].get("relationCandidates", [])
        if candidate["type"] == "incorporated_into_alternative"
    ]
    return request("extract entities and relations", data), context


def _proof(item: dict[str, Any], units: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(item, dict) or not isinstance(item.get("unit"), str):
        raise ValueError("invalid graph evidence shape")
    alias, quote = item.get("unit"), item.get("quote")
    unit = units.get(alias)
    if (
        unit is None
        or not isinstance(quote, str)
        or len(quote.strip()) < 2
        or len(quote) > 850
    ):
        raise ValueError("missing graph evidence")
    if unit["text"].count(quote) != 1:
        raise ValueError("graph quote is absent or ambiguous")
    left = unit["text"].index(quote)
    return {
        **unit,
        "text": quote,
        "start": unit["start"] + left,
        "end": unit["start"] + left + len(quote),
        "unitId": unit["id"],
    }


def validate_extraction(
    output: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Reject invented references and preserve new identities as private candidates."""
    nodes = {
        key: dict(value, identityStatus="source_bound")
        for key, value in context["aliases"].items()
    }
    created = output.get("entities")
    relations = output.get("relations")
    if (
        not isinstance(created, list)
        or not isinstance(relations, list)
        or len(created) > 4
        or len(relations) > 6
    ):
        raise ValueError("invalid extraction lists")
    for item in created:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("id"), str)
            or item.get("id") not in {"N1", "N2", "N3", "N4"}
            or item["id"] in nodes
        ):
            raise ValueError("invalid new graph alias")
        proof = _proof(item, context["units"])
        if item.get("kind") not in {
            "person",
            "organization",
            "bill",
            "policy",
        } or not isinstance(item.get("name"), str):
            raise ValueError("invalid new graph identity")
        if not 1 <= len(item["name"]) <= 100 or proof["text"].count(item["name"]) != 1:
            raise ValueError("new name lacks exact evidence")
        name_start = proof["start"] + proof["text"].index(item["name"])
        identity = "candidate_" + fingerprint(
            [
                proof["documentId"],
                proof["documentVersion"],
                proof["extractionVersion"],
                proof["segmentId"],
                item["kind"],
                item["name"],
                name_start,
                name_start + len(item["name"]),
            ]
        )
        nodes[item["id"]] = {
            "id": identity,
            "kind": item["kind"],
            "name": item["name"],
            "identifiers": [],
            "identityStatus": "pending",
            "evidence": [proof],
        }
    edges = {}
    for item in relations:
        if (
            not isinstance(item, dict)
            or any(not isinstance(item.get(key), str) for key in ("s", "t", "type"))
            or item.get("s") not in nodes
            or item.get("t") not in nodes
            or item.get("type") not in RELATION_TYPES
        ):
            raise ValueError("invalid graph relation")
        subject, target = nodes[item["s"]], nodes[item["t"]]
        if subject["id"] == target["id"]:
            raise ValueError("self relation is unsupported")
        if not valid_relation_endpoints(item["type"], subject["kind"], target["kind"]):
            raise ValueError("invalid relation endpoints")
        if (
            item["type"] in {"lead_sponsor", "co_sponsor"}
            and context.get("documentSourceKey") == "lawmaking-bill-detail"
            and target["id"] != context.get("documentBillId")
        ):
            raise ValueError("sponsor relation must target the record bill")
        allowed_lineage = context.get("allowedLineagePairs")
        if (
            item["type"] == "incorporated_into_alternative"
            and allowed_lineage is not None
            and [subject["id"], target["id"]] not in allowed_lineage
        ):
            continue
        proof = _proof(item, context["units"])
        document_identity_supported = False
        for alias, entity in ((item["s"], subject), (item["t"], target)):
            record_bound = (
                item["type"] == "concerns"
                and alias == item["s"]
                and entity["kind"] == "bill"
                and context.get("documentBillId") == entity["id"]
                and context.get("documentSourceKey") == "lawmaking-bill-detail"
                and any(
                    identifier
                    == {
                        "namespace": "ASSEMBLY_BILL_NUMBER",
                        "value": context.get("documentRecordKey"),
                    }
                    for identifier in entity.get("identifiers", [])
                )
            )
            source_form = context.get("sourceForms", {}).get(alias)
            supported = (
                entity["name"] in proof["text"]
                or isinstance(source_form, str)
                and source_form in proof["text"]
                and same_spelling_ignoring_space(source_form, entity["name"])
            ) or (
                entity["kind"] != "person"
                and any(
                    len(identifier["value"]) >= 4
                    and identifier["value"] in proof["text"]
                    for identifier in entity.get("identifiers", [])
                )
            )
            if not supported and not record_bound:
                raise ValueError("relation endpoint lacks quoted identity support")
            document_identity_supported |= record_bound and not supported
        relation_cue = bool(
            re.search(
                r"관한|관련|주제|대상|기록|concerns|about|records",
                proof["text"],
                re.IGNORECASE,
            )
        )
        negated = bool(
            re.search(
                r"무관|관련.{0,8}없|않|아니|not |unrelated",
                proof["text"],
                re.IGNORECASE,
            )
        )
        edge = {
            "source": subject["id"],
            "target": target["id"],
            "type": item["type"],
            "evidence": [proof],
            "decision": "pending",
            "endpointSupported": True,
            "relationCueSupported": relation_cue and not negated,
            **(
                {"documentIdentitySupported": True}
                if document_identity_supported
                else {}
            ),
        }
        edge_id = "edge_" + fingerprint(edge)
        edges[edge_id] = {"id": edge_id, **edge}
    return {
        "nodes": list(nodes.values()),
        "edges": list(edges.values()),
        "public": False,
    }


def community_task(
    members: list[dict[str, Any]],
    proofs: list[dict[str, Any]],
    *,
    level: int,
    links: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Request all memberships and grounded community reports from the model."""
    aliases = {f"E{i + 1}": item for i, item in enumerate(members)}
    units = {f"S{i + 1}": proof for i, proof in enumerate(proofs)}
    member_alias = {item["id"]: alias for alias, item in aliases.items()}
    proof_alias = {fingerprint(proof): alias for alias, proof in units.items()}
    data = {
        "members": [
            {
                "id": key,
                "name": item.get("name") or item.get("title"),
                "kind": item.get("kind", "community"),
                **({"summary": item["summary"]} if item.get("summary") else {}),
            }
            for key, item in aliases.items()
        ],
        "sources": {key: proof["text"] for key, proof in units.items()},
        "relations": [
            {
                "s": member_alias[edge["source"]],
                "t": member_alias[edge["target"]],
                "role": edge["type"],
                "proofs": [
                    proof_alias[fingerprint(p)]
                    for p in edge["evidence"]
                    if fingerprint(p) in proof_alias
                ],
            }
            for edge in (links or [])
            if edge["source"] in member_alias and edge["target"] in member_alias
        ],
        "schema": {
            "groups": [
                {
                    "title": "short theme",
                    "members": ["E1"],
                    "summary": "short grounded report",
                    "claims": [
                        {
                            "text": "fact",
                            "unit": "S1",
                            "quote": "exact source substring",
                        }
                    ],
                }
            ]
        },
        "rules": "Partition ALL member IDs once into 1..3 topical communities. At most 2 factual claims/group. Each claim needs supplied source. Empty claims/summary if source insufficient. Do not invent common goals or party agreement. No internal IDs like E1 in titles or claims; use member names. Describe scheduled actions as scheduled, never completed.",
    }
    return request(
        "assign communities and write evidence-backed reports",
        data,
        provider_tokenization=level == 0,
    ), {
        "aliases": aliases,
        "units": units,
        "level": level,
        "output_contract": OUTPUT_CONTRACT,
    }


def validate_report(output: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Validate complete memberships and attach immutable original citations."""
    groups, assigned = output.get("groups"), set()
    maximum = (
        len(context["aliases"])
        if context.get("output_contract")
        in {
            COMPLETE_COMMUNITY_CONTRACT,
            PRECISE_COMMUNITY_CONTRACT,
            ASSIGNMENT_COMMUNITY_CONTRACT,
            SHORT_QUOTE_COMMUNITY_CONTRACT,
            QUOTE_OPTIONS_COMMUNITY_CONTRACT,
        }
        else 3
    )
    if not isinstance(groups, list) or not 1 <= len(groups) <= maximum:
        raise ValueError("invalid community groups")
    result = []
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError("invalid community group shape")
        members, claims = group.get("members"), group.get("claims")
        if (
            not isinstance(members, list)
            or not members
            or not isinstance(claims, list)
            or len(claims) > 2
            or any(not isinstance(member, str) for member in members)
        ):
            raise ValueError("invalid community members or claims")
        if any(m not in context["aliases"] or m in assigned for m in members) or len(
            set(members)
        ) != len(members):
            raise ValueError("unknown or duplicate community member")
        assigned.update(members)
        if (
            not isinstance(group.get("title"), str)
            or not 1 <= len(group["title"]) <= 100
        ):
            raise ValueError("invalid community title")
        if not isinstance(group.get("summary"), str) or len(group["summary"]) > 500:
            raise ValueError("invalid community summary")
        if group["summary"] and not claims:
            raise ValueError("community prose needs evidenced claims")
        facts = [
            {"text": claim["text"], "evidence": _proof(claim, context["units"])}
            for claim in claims
            if isinstance(claim, dict)
            and isinstance(claim.get("text"), str)
            and 1 <= len(claim["text"]) <= 250
        ]
        if len(facts) != len(claims):
            raise ValueError("invalid community claim")
        if any(
            claim_quality_flags(fact["text"], fact["evidence"]["text"])
            for fact in facts
        ):
            raise ValueError("community claim quality requires review")
        member_ids = [context["aliases"][m]["id"] for m in members]
        result.append(
            {
                "id": "community_"
                + fingerprint(
                    [
                        GROUP_ID_VERSION,
                        context.get("artifact_key"),
                        context["level"],
                        sorted(member_ids),
                        group["title"],
                    ]
                ),
                "title": group["title"],
                "members": member_ids,
                "summary": " ".join(fact["text"] for fact in facts),
                "claims": facts,
                "level": context["level"],
                "decision": "pending",
            }
        )
    if assigned != set(context["aliases"]):
        raise ValueError("community membership coverage incomplete")
    return {"groups": result, "level": context["level"], "public": False}
