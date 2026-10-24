"""Build bounded, evidence-preserving requests for grounded answers."""

from typing import Any

from parliament_worker.graphrag.output_contract import ANSWER_CONTRACT
from parliament_worker.graphrag.prompts import request


def _answer_request(
    question: str,
    proofs: list[dict[str, Any]],
    *,
    context_text: Any = None,
    plain_claims: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Pin source aliases while requesting at most four supported claims."""
    units = {f"S{i + 1}": proof for i, proof in enumerate(proofs)}
    data = {
        "question": question,
        "graph_or_reports": context_text or [],
        "sources": {key: proof["text"] for key, proof in units.items()},
        "sourceUrls": {key: proof.get("sourceUrl", "") for key, proof in units.items()},
        "schema": {
            "claims": [
                {
                    "text": "short factual answer",
                    "unit": "S1",
                    "quote": "exact supporting substring",
                }
            ],
        },
        "rules": (
            "Answer only within supplied records. At most 4 claims, each with"
            " an exact source proof. This excerpt may support any explicit part"
            " of a compound question. Do not require this excerpt to cover the"
            " other parts. Return only directly supported facts; use claims=[]"
            " when none are supported. Do not assert causal impact, attendance"
            " or policy credit. Keep planned actions distinct from completed"
            " actions. Names, dates and roles must stay unchanged. Use each"
            " source URL to distinguish a bill proposal from a ministry"
            " announcement. State what a bill proposal proposes, not what is"
            " already enacted. Attribute a ministry announcement's actions"
            " and outcomes to that announcement; do not present them as"
            " independently verified implementation or effects."
        )
        + (
            " For current-tenure questions, an undated roster or a past office"
            " listing cannot prove current officeholding. Return claims=[] for"
            " unproven current tenure. Do not invent collection dates or infer"
            " continued tenure from a source label such as current."
            if "재임" in question and ("현재" in question or "지금" in question)
            else ""
        )
        + (
            " Do not repeat the source quote in claim text or add parenthetical"
            " evidence there; select the separate proof field instead."
            if plain_claims
            else ""
        ),
    }
    return request("answer grounded question", data), {
        "units": units,
        "question": question,
        "output_contract": ANSWER_CONTRACT,
    }


def community_answer_requests(
    question: str, proofs: list[dict[str, Any]], context: list[dict[str, str]]
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Split an oversized community group without dropping source proofs.

    Args:
        question: User question pinned to the index snapshot.
        proofs: Ordered exact source excerpts in the community group.
        context: Derived community title and summary.

    Returns:
        Bounded requests whose proof contexts cover every supplied proof once.

    Raises:
        ValueError: If a single source excerpt exceeds the request allowance.
    """
    batches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for proof in proofs:
        candidate = current + [proof]
        try:
            _answer_request(question, candidate, context_text=context)
        except ValueError:
            if current:
                batches.append(_answer_request(question, current, context_text=context))
                current = [proof]
            else:
                current = candidate
            try:
                _answer_request(question, current, context_text=context)
            except ValueError:
                # Derived context is expendable; the original excerpt is not.
                batches.append(_answer_request(question, current))
                current = []
        else:
            current = candidate
    if current:
        batches.append(_answer_request(question, current, context_text=context))
    return batches
