"""Local graph traversal and global community map/reduce with fixed citations."""

from typing import Any

from parliament_worker.graphrag.answer_requests import (
    _answer_request,
    community_answer_requests,
)
from parliament_worker.graphrag.answer_validation import validate_answer
from parliament_worker.graphrag.claim_quality_audit import claim_quality_flags
from parliament_worker.graphrag.index import (
    current_artifacts,
    select_snapshot_artifacts,
    source_dependency,
    source_manifest,
)
from parliament_worker.graphrag.inputs import fingerprint
from parliament_worker.graphrag.prompts import PROMPT_VERSION
from parliament_worker.graphrag.query_status import question_status
from parliament_worker.graphrag.query_terms import (
    diversify_evidence as _diversify_evidence,
)
from parliament_worker.graphrag.query_terms import evidence_score as _evidence_score
from parliament_worker.graphrag.query_terms import (
    is_name_place_label as _is_name_place_label,
)
from parliament_worker.graphrag.query_terms import promote_named_endpoint_evidence
from parliament_worker.graphrag.query_terms import role_hints as _role_hints
from parliament_worker.graphrag.query_terms import score as _score
from parliament_worker.graphrag.source_entities import source_only_person_nodes
from parliament_worker.graphrag.source_safety import (
    contains_contact,
    safe_context_text,
)
from parliament_worker.graphrag.store import GraphStore
from parliament_worker.knowledge.review import ID_PATTERN

QUERY_PLAN_VERSION = "community-and-source-maps-v7"
LOCAL_RETRIEVAL_VERSION = "answerable-evidence-v12"


def _safe_community_claims(group: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep a flagged model claim from seeding a new private answer."""
    return [
        claim
        for claim in group["claims"]
        if not contains_contact(claim["evidence"]["text"])
        and not claim_quality_flags(claim["text"], claim["evidence"]["text"])
    ]


def _evidence_key(proof: dict[str, Any]) -> str:
    """Match a pinned quote to its source unit despite derived unitId metadata."""
    return fingerprint({key: value for key, value in proof.items() if key != "unitId"})


def _snapshot(store: GraphStore, index_snapshot: dict[str, Any] | None = None) -> str:
    sources = index_snapshot["sources"] if index_snapshot else store.sources()
    graphs = (
        index_snapshot["graphs"]
        if index_snapshot
        else current_artifacts(store, "graph")
    )
    reports = (
        index_snapshot["reports"]
        if index_snapshot
        else current_artifacts(store, "community")
    )
    return fingerprint(
        {
            "sources": [source_dependency(s) for s in sources],
            "graphs": [[a["key"], a["version"]] for a in graphs],
            "reports": [[a["key"], a["version"]] for a in reports],
        }
    )


def compact_question_dependency(dependency: dict[str, Any]) -> dict[str, Any]:
    """Pin the same source set without copying every source into each job."""
    return {
        **{key: value for key, value in dependency.items() if key != "sources"},
        "source_manifest": source_manifest(dependency["sources"]),
    }


def _local_context(
    store: GraphStore,
    question: str,
    *,
    entity_id: str | None = None,
    index_snapshot: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    graphs = (
        index_snapshot["graphs"]
        if index_snapshot
        else current_artifacts(store, "graph")
    )
    sources = index_snapshot["sources"] if index_snapshot else store.sources()
    nodes, edges, proofs = {}, {}, {}
    proof_priority: dict[str, int] = {}
    for artifact in graphs:
        nodes.update({node["id"]: node for node in artifact["payload"]["nodes"]})
        edges.update({edge["id"]: edge for edge in artifact["payload"]["edges"]})
    if entity_id is not None:
        if entity_id not in nodes:
            nodes.update(source_only_person_nodes(sources, target_id=entity_id))
        if (
            entity_id not in nodes
            or nodes[entity_id]["kind"] != "person"
            or nodes[entity_id].get("identityConflict")
        ):
            raise ValueError("unknown scoped person")
        seeds = {entity_id}
    else:
        ranked = sorted(
            nodes.values(),
            key=lambda n: (n["name"] in question, _score(question, n["name"])),
            reverse=True,
        )
        exact = {node["id"] for node in ranked if node["name"] in question}
        seeds = exact or {
            n["id"]
            for n in ranked[:5]
            if n["name"] in question or _score(question, n["name"]) > 0
        }
        seeds = set(sorted(seeds)[:5])
    neighbors = set(seeds)
    for _ in range(2):
        frontier = set(neighbors)
        for edge in edges.values():
            if edge["source"] in frontier or edge["target"] in frontier:
                additions = sorted({edge["source"], edge["target"]} - neighbors)
                neighbors.update(additions[: max(0, 30 - len(neighbors))])
    edge_context = []
    hinted = _role_hints(question)
    for edge in sorted(edges.values(), key=lambda e: e["id"]):
        if (
            edge["source"] in neighbors
            and edge["target"] in neighbors
            and (entity_id is None or entity_id in {edge["source"], edge["target"]})
        ):
            edge_context.append(
                {
                    "from": nodes[edge["source"]]["name"],
                    "to": nodes[edge["target"]]["name"],
                    "role": edge["type"],
                    "decision": edge["decision"],
                }
            )
            anchored = edge["source"] in seeds or edge["target"] in seeds
            priority = 3 if anchored and edge["type"] in hinted else int(anchored)
            for proof in edge["evidence"]:
                if contains_contact(proof["text"]):
                    continue
                key = _evidence_key(proof)
                proofs.setdefault(key, proof)
                proof_priority[key] = max(proof_priority.get(key, 0), priority)
    report_artifacts = (
        index_snapshot["reports"]
        if index_snapshot
        else current_artifacts(store, "community")
    )
    for artifact in report_artifacts:
        for group in artifact["payload"]["groups"]:
            if (
                entity_id in group["members"]
                if entity_id is not None
                else bool(set(group["members"]) & neighbors)
            ):
                for claim in group["claims"]:
                    proof = claim["evidence"]
                    if not contains_contact(proof["text"]):
                        proofs.setdefault(_evidence_key(proof), proof)
    # A sparse graph still exposes coverage and can return source-only context.
    # This is visible in retrieval metadata, not presented as a finished graph.
    for source in sources:
        if entity_id is not None and not any(
            entity["id"] == entity_id for entity in source["payload"]["entities"]
        ):
            continue
        for unit in source["payload"]["units"]:
            if (
                not contains_contact(unit["text"])
                and _evidence_score(question, unit["text"], unit.get("documentId", ""))
                > 0
            ):
                proofs.setdefault(_evidence_key(unit), unit)
    ranked_proofs = sorted(
        proofs.values(),
        key=lambda proof: (
            _evidence_score(question, proof["text"], proof.get("documentId", ""))
            + 0.06 * proof_priority.get(_evidence_key(proof), 0),
            _evidence_score(question, proof["text"], proof.get("documentId", "")),
        ),
        reverse=True,
    )
    ranked_proofs = _diversify_evidence(question, ranked_proofs)
    ranked_proofs = promote_named_endpoint_evidence(
        question, entity_id, nodes, edges.values(), ranked_proofs
    )
    retrieved_count = len(ranked_proofs)
    if hinted or "활동" in question:
        ranked_proofs = [
            proof for proof in ranked_proofs if not _is_name_place_label(proof["text"])
        ]
    context = [edge for edge in edge_context if edge["decision"] == "approved"][:6]
    selected = []
    for proof in ranked_proofs:
        try:
            _answer_request(
                question,
                selected + [proof],
                context_text=context,
                plain_claims=True,
            )
        except ValueError:
            continue
        selected.append(proof)
        if len(selected) >= 6:
            break
    return (
        selected,
        context,
        {
            "seedEntities": sorted(seeds),
            **({"scopedEntity": entity_id} if entity_id is not None else {}),
            **(
                {"sourceOnlyIdentity": True}
                if entity_id is not None and nodes[entity_id].get("sourceOnly")
                else {}
            ),
            "neighborEntities": len(neighbors),
            "retrievedProofs": retrieved_count,
            "weakRoleProofsExcluded": retrieved_count - len(ranked_proofs),
            "includedProofs": len(selected),
            "contextLimited": len(selected) < len(ranked_proofs),
            "graphEdges": len(edge_context),
        },
    )


def submit_question(
    store: GraphStore,
    question: str,
    mode: str,
    model_signature: str,
    *,
    entity_id: str | None = None,
) -> dict[str, Any]:
    """Pin a private question to an index version and schedule durable model work."""
    if (
        not isinstance(question, str)
        or not question.strip()
        or len(question) > 1000
        or len(question.encode()) > 1200
        or mode not in {"local", "global"}
        or (
            entity_id is not None
            and (
                not isinstance(entity_id, str)
                or mode != "local"
                or not ID_PATTERN.fullmatch(entity_id)
            )
        )
    ):
        raise ValueError("invalid GraphRAG question")
    question = question.strip()
    index_snapshot = store.query_snapshot()
    index_snapshot["graphs"] = select_snapshot_artifacts(index_snapshot, "graph")
    index_snapshot["reports"] = select_snapshot_artifacts(index_snapshot, "community")
    snapshot = _snapshot(store, index_snapshot)
    identifier = "question_" + fingerprint(
        [question, mode, snapshot, model_signature, PROMPT_VERSION, QUERY_PLAN_VERSION]
        + ([LOCAL_RETRIEVAL_VERSION] if mode == "local" else [])
        + ([entity_id] if entity_id is not None else [])
    )
    cached = store.get_artifact("question", identifier)
    if cached:
        return question_status(store, identifier)
    sources = [source_dependency(s) for s in index_snapshot["sources"]]
    dependency = {
        "sources": sources,
        "snapshot": snapshot,
        "model_signature": model_signature,
    }
    job_dependency = compact_question_dependency(dependency)
    question_payload = {
        "id": identifier,
        "question": question,
        "mode": mode,
        "state": "queued",
        "snapshot": snapshot,
        "jobs": [],
        "coverage": index_snapshot["coverage"],
        "private": True,
        "planVersion": QUERY_PLAN_VERSION
        + ("+" + LOCAL_RETRIEVAL_VERSION if mode == "local" else ""),
        **({"entityId": entity_id} if entity_id is not None else {}),
    }
    plans = []
    if mode == "local":
        proofs, context, retrieval = _local_context(
            store, question, entity_id=entity_id, index_snapshot=index_snapshot
        )
        question_payload["retrieval"] = retrieval
        if proofs:
            body, proof_context = _answer_request(
                question, proofs, context_text=context, plain_claims=True
            )
            plans.append(
                {
                    "kind": "query_local",
                    "key": identifier,
                    "request": body,
                    "context": {
                        **job_dependency,
                        **proof_context,
                        "artifact_key": identifier,
                        "question_id": identifier,
                    },
                }
            )
    else:
        reports = index_snapshot["reports"]
        levels = [report["payload"]["level"] for report in reports]
        question_payload["retrieval"] = {
            "communityLevels": [],
            "reports": 0,
            "communityMapTasks": 0,
            "sourceUnits": 0,
            "sourceMapTasks": 0,
            "sensitiveUnitsExcluded": 0,
            "sensitiveCommunityProofsExcluded": 0,
            "qualityFlaggedCommunityClaimsExcluded": 0,
            "mapTasks": 0,
        }
        if levels:
            # Use the complete current hierarchy frontier. Uneven or unfinished
            # parents must not hide independent lower-level communities.
            parents = [
                report
                for report in reports
                if report["payload"]["level"] > 0
                and all(
                    _safe_community_claims(group)
                    for group in report["payload"]["groups"]
                )
            ]
            covered = {
                (child["key"], child["version"])
                for report in parents
                for child in report["dependency"].get("children", [])
                if child["kind"] == "community"
            }
            chosen = [
                report
                for report in reports
                if (report["key"], report["version"]) not in covered
                and (report["payload"]["level"] == 0 or report in parents)
            ]
            question_payload["retrieval"] = {
                "communityLevels": sorted(
                    {report["payload"]["level"] for report in chosen}
                ),
                "reports": len(chosen),
                "communityMapTasks": 0,
                "sourceUnits": 0,
                "sourceMapTasks": 0,
                "sensitiveUnitsExcluded": 0,
                "sensitiveCommunityProofsExcluded": 0,
                "qualityFlaggedCommunityClaimsExcluded": 0,
                "mapTasks": 0,
            }
            for report in chosen:
                for index, group in enumerate(report["payload"]["groups"]):
                    safe_claims = _safe_community_claims(group)
                    proofs = [claim["evidence"] for claim in safe_claims]
                    for claim in group["claims"]:
                        if claim in safe_claims:
                            continue
                        proof = claim["evidence"]
                        if contains_contact(proof["text"]):
                            question_payload["retrieval"][
                                "sensitiveCommunityProofsExcluded"
                            ] += 1
                        else:
                            question_payload["retrieval"][
                                "qualityFlaggedCommunityClaimsExcluded"
                            ] += 1
                    if not proofs:
                        continue
                    context = [
                        {
                            "title": safe_context_text(group["title"]),
                            "summary": safe_context_text(
                                " ".join(claim["text"] for claim in safe_claims)
                            ),
                        }
                    ]
                    for part, (body, proof_context) in enumerate(
                        community_answer_requests(question, proofs, context)
                    ):
                        plans.append(
                            {
                                "kind": "query_map",
                                "key": fingerprint(
                                    [identifier, report["version"], index, part]
                                ),
                                "request": body,
                                "context": {
                                    **job_dependency,
                                    **proof_context,
                                    "artifact_key": identifier + ":" + str(len(plans)),
                                    "question_id": identifier,
                                },
                            }
                        )
            question_payload["retrieval"]["communityMapTasks"] = len(plans)
        for source in index_snapshot["sources"]:
            document = source["payload"]["document"]
            for unit in source["payload"]["units"]:
                question_payload["retrieval"]["sourceUnits"] += 1
                if contains_contact(unit["text"]) or contains_contact(
                    document["title"]
                ):
                    question_payload["retrieval"]["sensitiveUnitsExcluded"] += 1
                    continue
                body, proof_context = _answer_request(
                    question,
                    [unit],
                    context_text=[{"documentTitle": document["title"]}],
                )
                plans.append(
                    {
                        "kind": "query_map",
                        "key": fingerprint(
                            [identifier, "source", source["scope"], unit["id"]]
                        ),
                        "request": body,
                        "context": {
                            **job_dependency,
                            **proof_context,
                            "artifact_key": identifier + ":" + str(len(plans)),
                            "question_id": identifier,
                        },
                    }
                )
        question_payload["retrieval"]["sourceMapTasks"] = (
            question_payload["retrieval"]["sourceUnits"]
            - question_payload["retrieval"]["sensitiveUnitsExcluded"]
        )
        question_payload["retrieval"]["mapTasks"] = len(plans)
    if plans:
        question_payload["jobs"] = store.enqueue_many(plans)
    else:
        question_payload.update(
            state="insufficient_evidence", answer="", claims=[], insufficient=True
        )
    store.put_artifact("question", identifier, dependency, question_payload)
    return {"id": identifier, "state": question_payload["state"], "mode": mode}


def plan_question_reductions(store: GraphStore) -> int:
    """Plan bounded reductions while keeping every claim paired with its source."""
    from parliament_worker.graphrag.reduction import plan_reductions

    return plan_reductions(store)
