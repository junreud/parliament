"""Conservative lexical signals for ranking fixed GraphRAG evidence."""

import re
from collections import Counter
from collections.abc import Iterable
from typing import Any

_PLACE = r"[가-힣]{2,12}(?:도|시|군|구)"
_NAME = r"[가-힣]{2,5}"
NAME_PLACE_LABEL = re.compile(
    rf"(?:{_PLACE}\s+){{1,3}}{_NAME}|{_NAME}(?:\s+{_PLACE}){{1,3}}"
)


def is_name_place_label(text: str) -> bool:
    """Identify short directory labels that state no action or residence."""
    return bool(NAME_PLACE_LABEL.fullmatch(text.strip()))


def terms(text: str) -> set[str]:
    """Return whole tokens, exact numbers, and Korean text fragments."""
    tokens = set(re.findall(r"[\w]+", text.lower())) | set(re.findall(r"\d+", text))
    return tokens | {
        fragment
        for token in tokens
        for i in range(max(0, len(token) - 2))
        if re.search(r"[가-힣]", fragment := token[i : i + 3])
    }


def score(question: str, text: str) -> float:
    """Rank a fixed evidence span by lexical overlap with the question."""
    left, right = terms(question), terms(text)
    return len(left & right) / max(1, len(right))


def evidence_score(question: str, text: str, document_id: str = "") -> float:
    """Favor informative answer passages over matching titles and name labels."""
    bill_match = any(
        document_id == f"doc-bill-{number}"
        for number in re.findall(r"(?<!\d)\d{7}(?!\d)", question)
    )
    left, right = terms(question), terms(text)
    overlap = len(left & right)
    if not overlap:
        return 0.5 if bill_match else 0.0
    precision = overlap / len(right)
    recall = overlap / len(left)
    detail = 0.25 + 0.75 * min(len(text.strip()) / 90, 1)
    return 2 * precision * recall / (precision + recall) * detail + (
        0.5 if bill_match else 0.0
    )


def diversify_evidence(
    question: str, ranked: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Reserve proof space for a second document in comparison questions."""
    if not ranked or not (
        "각각" in question
        or "비교" in question
        or (re.search(r"(?<!\d)\d{7}(?!\d)", question) and "발표" in question)
    ):
        return ranked
    first_document = ranked[0].get("documentId")
    alternate = next(
        (
            proof.get("documentId")
            for proof in ranked[1:]
            if proof.get("documentId")
            and proof.get("documentId") != first_document
            and evidence_score(question, proof["text"], proof.get("documentId", "")) > 0
        ),
        None,
    )
    if not first_document or not alternate:
        return ranked
    promoted = [proof for proof in ranked if proof.get("documentId") == alternate][:2]
    promoted_ids = {proof["id"] for proof in promoted}
    return [ranked[0], *promoted] + [
        proof for proof in ranked[1:] if proof["id"] not in promoted_ids
    ]


def promote_named_endpoint_evidence(
    question: str,
    scoped_person_id: str | None,
    nodes: dict[str, dict[str, Any]],
    edges: Iterable[dict[str, Any]],
    ranked: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Reserve one distinct proof for each named neighbor of a scoped person.

    Args:
        question: The user's full question.
        scoped_person_id: Explicit person ID, if the query is person-scoped.
        nodes: Current graph nodes keyed by stable ID.
        edges: Current graph edges with their pinned source proofs.
        ranked: Already ranked and deduplicated proof candidates.

    Returns:
        The same proofs, with evidence for each named neighbor first. A shared
        person-status proof cannot displace both distinct organization rules.
    """
    if scoped_person_id is None or not ranked:
        return ranked
    available = {item["id"]: item for item in ranked}
    facets: dict[str, dict[str, Any]] = {}
    for edge in edges:
        endpoints = (edge["source"], edge["target"])
        if scoped_person_id not in endpoints:
            continue
        neighbor = endpoints[1] if endpoints[0] == scoped_person_id else endpoints[0]
        name = nodes.get(neighbor, {}).get("name", "")
        if not name or name not in question:
            continue
        facet = facets.setdefault(
            neighbor, {"position": question.index(name), "proofs": {}}
        )
        for item in edge.get("evidence", []):
            if item["id"] in available:
                facet["proofs"][item["id"]] = available[item["id"]]
    if len(facets) < 2:
        return ranked
    frequency = Counter(
        identifier for facet in facets.values() for identifier in facet["proofs"]
    )
    promoted: list[str] = []
    for facet in sorted(facets.values(), key=lambda item: item["position"]):
        choices = [
            item for item in facet["proofs"].values() if item["id"] not in promoted
        ]
        if choices:
            best = min(
                choices,
                key=lambda item: (
                    frequency[item["id"]],
                    -evidence_score(question, item["text"], item.get("documentId", "")),
                    item["id"],
                ),
            )
            promoted.append(best["id"])
    promoted_ids = set(promoted)
    return [available[identifier] for identifier in promoted] + [
        item for item in ranked if item["id"] not in promoted_ids
    ]


def role_hints(question: str) -> set[str]:
    """Identify explicit action words solely for retrieval ordering."""
    roles = set()
    if "발의" in question:
        roles.update({"lead_sponsor", "co_sponsor"})
    if "표결" in question or "투표" in question:
        roles.add("voter")
    if "직위" in question or "장관" in question or "소속" in question:
        roles.add("holds_office")
    if "발언" in question:
        roles.add("speaker")
    return roles
