"""Audit private question evidence without treating model prose as verified fact."""

import hashlib
import re
from collections import Counter
from typing import Any

from parliament_worker.graphrag.answer_quality import editorial_reasons
from parliament_worker.graphrag.answer_temporal import answer_coverage_findings
from parliament_worker.graphrag.job_codec import decode_job
from parliament_worker.graphrag.query import question_status
from parliament_worker.graphrag.reduction import _source_facets
from parliament_worker.graphrag.store import GraphStore


def _answer_coverage_findings(
    question: dict[str, Any], final: dict[str, Any] | None
) -> list[str]:
    """Flag a missing current-tenure part in a completed private answer."""
    if final is None or final["payload"].get("insufficient") is True:
        return []
    prompt = question["payload"].get("question", "")
    answer = final["payload"].get("answer", "")
    if not isinstance(prompt, str) or not isinstance(answer, str):
        return []
    return answer_coverage_findings(prompt, answer)


def _claim_id(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _current_jobs(store: GraphStore, question_id: str) -> list[dict[str, Any]]:
    """Read the newest saved attempt for each logical question job."""
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    with store._transaction(write=False) as db:
        rows = db.execute(
            "SELECT data FROM jobs WHERE kind IN "
            "('query_local','query_map','query_reduce') "
            "AND json_extract(data,'$.context.question_id')=? ORDER BY rowid",
            (question_id,),
        )
        for (data,) in rows:
            job = decode_job(data)
            key = job["context"].get("artifact_key")
            if isinstance(key, str):
                latest[(job["kind"], key)] = job
    return list(latest.values())


def _proof_matches(proof: Any, units: dict[str, list[dict[str, Any]]]) -> bool:
    if (
        not isinstance(proof, dict)
        or not isinstance(proof.get("text"), str)
        or not isinstance(proof.get("unitId"), str)
    ):
        return False
    if type(proof.get("start")) is not int or type(proof.get("end")) is not int:
        return False
    matching = units.get(proof.get("unitId"), [])
    for unit in matching:
        if any(
            proof.get(field) != unit.get(field)
            for field in (
                "documentId",
                "documentVersion",
                "extractionVersion",
                "segmentId",
                "sourceUrl",
            )
        ):
            continue
        offset = proof["start"] - unit["start"]
        quote = proof["text"]
        if (
            0 <= offset
            and proof["end"] - proof["start"] == len(quote)
            and unit["text"][offset : offset + len(quote)] == quote
            and proof["end"] <= unit["end"]
        ):
            return True
    return False


def _inspect_result(
    result: Any,
    *,
    artifact_key: str,
    units: dict[str, list[dict[str, Any]]],
    source_facets: dict[str, str],
    structural: list[dict[str, str]],
    editorial: list[dict[str, str]],
    unique_claims: set[str],
) -> int:
    if not isinstance(result, dict) or not isinstance(result.get("claims"), list):
        structural.append({"artifactKey": artifact_key, "reason": "invalid_result"})
        return 0
    if result.get("private") is not True or result.get("reviewRequired") is not True:
        structural.append(
            {"artifactKey": artifact_key, "reason": "publication_gate_missing"}
        )
    for claim in result["claims"]:
        if not isinstance(claim, dict) or not isinstance(claim.get("text"), str):
            structural.append({"artifactKey": artifact_key, "reason": "invalid_claim"})
            continue
        text = claim["text"]
        claim_digest = _claim_id(text)
        unique_claims.add(claim_digest)
        proof = claim.get("evidence")
        if not _proof_matches(proof, units):
            structural.append(
                {
                    "artifactKey": artifact_key,
                    "claimDigest": claim_digest,
                    "reason": "evidence_span_mismatch",
                }
            )
        facet = (
            source_facets.get(proof.get("sourceUrl"))
            if isinstance(proof, dict)
            else None
        )
        for reason in editorial_reasons(claim, facet):
            editorial.append(
                {
                    "artifactKey": artifact_key,
                    "claimDigest": claim_digest,
                    "reason": reason,
                }
            )
    return len(result["claims"])


def _source_facet_coverage(
    facets: dict[str, str],
    originals: list[dict[str, Any]],
    final: dict[str, Any] | None,
    units: dict[str, list[dict[str, Any]]],
) -> dict[str, dict[str, int]]:
    """Distinguish evidence available in maps from evidence in the final answer."""
    claims: dict[str, dict[str, set[tuple[str, str]]]] = {
        facet: {"mappedClaims": set(), "finalClaims": set()}
        for facet in sorted(set(facets.values()))
    }

    def include(result: Any, field: str) -> None:
        if not isinstance(result, dict):
            return
        for claim in result.get("claims", []):
            if not isinstance(claim, dict) or not isinstance(claim.get("text"), str):
                continue
            proof = claim.get("evidence")
            if (
                not isinstance(proof, dict)
                or not _proof_matches(proof, units)
                or editorial_reasons(claim, facets.get(proof.get("sourceUrl")))
            ):
                continue
            facet = facets.get(proof.get("sourceUrl"))
            if facet:
                claims[facet][field].add((proof["sourceUrl"], claim["text"]))

    for job in originals:
        if job["state"] == "completed":
            include(job["result"], "mappedClaims")
    if final:
        include(final["payload"], "finalClaims")
    return {
        facet: {field: len(values) for field, values in counts.items()}
        for facet, counts in claims.items()
    }


def audit_question(store: GraphStore, question_id: str) -> dict[str, Any]:
    """Check current question work and exact proofs, flagging editorial risks.

    Args:
        store: Private GraphRAG state containing the fixed question and jobs.
        question_id: Identifier returned by the question submission path.

    Returns:
        A private, text-free report. Structural checks do not establish factual
        entailment, identity accuracy, source-use rights, or publication approval.

    Raises:
        ValueError: If the question does not exist.
    """
    question = store.get_artifact("question", question_id)
    if question is None:
        raise ValueError("unknown graph question")
    status = (
        question_status(store, question_id)
        if "snapshot" in question["payload"]
        else question["payload"]
    )
    jobs = _current_jobs(store, question_id)
    original_key = re.compile(r"^" + re.escape(question_id) + r":\d+$")
    originals = [
        job
        for job in jobs
        if job["kind"] == "query_map"
        and original_key.fullmatch(job["context"]["artifact_key"])
    ]
    states = Counter(job["state"] for job in originals)
    units: dict[str, list[dict[str, Any]]] = {}
    for job in jobs:
        context_units = job["context"].get("units", {})
        if isinstance(context_units, dict):
            for unit in context_units.values():
                if isinstance(unit, dict) and isinstance(unit.get("id"), str):
                    units.setdefault(unit["id"], []).append(unit)

    structural: list[dict[str, str]] = []
    editorial: list[dict[str, str]] = []
    unique_claims: set[str] = set()
    source_facets = (
        _source_facets(store.sources())
        if question["payload"].get("mode") == "global"
        else {}
    )
    claims_checked = 0
    for job in jobs:
        if job["state"] == "completed":
            claims_checked += _inspect_result(
                job["result"],
                artifact_key=job["context"]["artifact_key"],
                units=units,
                source_facets=source_facets,
                structural=structural,
                editorial=editorial,
                unique_claims=unique_claims,
            )
    final = store.get_artifact("answer", question_id)
    if final:
        claims_checked += _inspect_result(
            final["payload"],
            artifact_key=question_id + ":final",
            units=units,
            source_facets=source_facets,
            structural=structural,
            editorial=editorial,
            unique_claims=unique_claims,
        )
    question_state = status["state"]
    if final and "snapshot" not in question["payload"]:
        question_state = "completed"
    facet_coverage = (
        _source_facet_coverage(source_facets, originals, final, units)
        if question["payload"].get("mode") == "global"
        else {}
    )
    return {
        "schema": "parliament-graphrag-answer-audit-v1",
        "questionId": question_id,
        "questionState": question_state,
        "outdatedIndex": status.get("outdatedIndex"),
        "mapJobs": {
            "completed": states["completed"],
            "total": len(originals),
            "failed": states["failed"] + states["obsolete"],
        },
        "allMapsComplete": (
            bool(originals) and states["completed"] == len(originals)
            if question["payload"].get("mode") == "global"
            else None
        ),
        "claimsChecked": claims_checked,
        "uniqueClaimsChecked": len(unique_claims),
        "structuralFindings": structural,
        "editorialFindings": editorial,
        "uniqueEditorialClaims": len({item["claimDigest"] for item in editorial}),
        "answerCoverageFindings": _answer_coverage_findings(question, final),
        "sourceFacets": facet_coverage,
        "publicationApproved": False,
        "private": True,
    }
