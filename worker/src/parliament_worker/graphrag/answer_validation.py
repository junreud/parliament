"""Validate private grounded answers against pinned source excerpts."""

from typing import Any

from parliament_worker.graphrag.answer_temporal import answer_coverage_findings
from parliament_worker.graphrag.prompts import _proof


def validate_answer(output: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Keep only cited claims; discarded model prose cannot leak facts.

    Args:
        output: Parsed model answer under the grounded-answer contract.
        context: Fixed source aliases used in the original request.

    Returns:
        A private answer built solely from exact cited source claims.
    """
    claims = output.get("claims")
    if (
        not isinstance(claims, list)
        or len(claims) > 4
        or type(output.get("insufficient")) is not bool
    ):
        raise ValueError("invalid grounded answer")
    result = []
    for claim in claims:
        if (
            not isinstance(claim, dict)
            or not isinstance(claim.get("text"), str)
            or not 1 <= len(claim["text"]) <= 350
        ):
            raise ValueError("invalid answer claim")
        result.append(
            {"text": claim["text"], "evidence": _proof(claim, context["units"])}
        )
    if output["insufficient"] and result:
        raise ValueError("contradictory insufficient answer")
    answer = "\n".join(dict.fromkeys(claim["text"] for claim in result))
    question = context.get("question", "")
    findings = (
        answer_coverage_findings(question, answer)
        if isinstance(question, str) and result
        else []
    )
    if findings:
        return {
            "answer": "",
            "claims": [],
            "insufficient": True,
            "private": True,
            "reviewRequired": True,
            "answerCoverageFindings": findings,
        }
    return {
        "answer": answer,
        "claims": result,
        "insufficient": not result,
        "private": True,
        "reviewRequired": True,
    }
