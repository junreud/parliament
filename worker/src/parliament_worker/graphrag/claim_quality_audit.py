"""Find private GraphRAG claims that need editorial review before publication."""

from collections import Counter
from typing import Any

from parliament_worker.graphrag.claim_quality import claim_quality_flags
from parliament_worker.graphrag.index import select_snapshot_artifacts


def audit_claim_quality(snapshot: dict[str, Any]) -> dict[str, Any]:
    """List review candidates from only current, source-bound private reports.

    Args:
        snapshot: A consistent GraphStore query snapshot.

    Returns:
        Private finding counts and precise report/evidence pointers.
    """
    reports = select_snapshot_artifacts(snapshot, "community")
    counts: Counter[str] = Counter()
    cases = []
    for report in reports:
        for group in report["payload"]["groups"]:
            for index, claim in enumerate(group["claims"]):
                counts["claims"] += 1
                quote = claim["evidence"]["text"]
                for flag in claim_quality_flags(claim["text"], quote):
                    counts[flag] += 1
                    cases.append(
                        {
                            "flag": flag,
                            "reportKey": report["key"],
                            "reportVersion": report["version"],
                            "level": report["payload"]["level"],
                            "groupId": group["id"],
                            "claimIndex": index,
                            "claimText": claim["text"],
                            "sourceUrl": claim["evidence"].get("sourceUrl"),
                            "evidenceId": claim["evidence"].get("id"),
                            "evidenceQuote": quote,
                            "reviewDecision": "pending",
                        }
                    )
    return {
        "schema": "parliament-graphrag-claim-quality-audit-v1",
        "public": False,
        "humanReviewed": False,
        "reportCount": len(reports),
        "counts": dict(sorted(counts.items())),
        "cases": cases,
    }
