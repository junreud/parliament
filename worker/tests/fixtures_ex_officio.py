"""Synthetic chair clauses exercise fixed URL contracts without operator files.

Official host, organization and selector constants describe the parser contract.
The person, document versions and statements below are fabricated test inputs;
they are neither collected evidence nor approval of a real public relationship.
"""

from typing import Any

from parliament_worker.graphrag.ex_officio import PRESIDENT_URL, RULES


def chair_batch(*, extra_rule: str | None = None) -> dict[str, Any]:
    """Build a private synthetic batch with independently owned evidence.

    Args:
        extra_rule: Optional single rule replacing the default two-rule batch.

    Returns:
        A fresh candidate batch suitable for source adapter regression tests.
    """
    batch: dict[str, Any] = {
        "id": "synthetic-chair-batch",
        "issueId": "synthetic-chair-issue",
        "entities": [],
        "documents": [],
        "evidence": [],
        "relations": [],
        "activities": [],
        "contexts": [],
    }

    def add(
        key: str,
        source_key: str,
        record_key: str,
        url: str,
        title: str,
        text: str,
        entity: dict[str, Any],
    ) -> None:
        evidence_id = f"ev-{key}"
        batch["entities"].append(
            entity | {"facts": [{"evidenceIds": [evidence_id]}], "tenures": []}
        )
        batch["documents"].append(
            {
                "id": f"doc-{key}",
                "sourceKey": source_key,
                "recordKey": record_key,
                "sourceUrl": url,
                "title": title,
                "version": f"synthetic-version-{key}",
                "extractionVersion": f"synthetic-extraction-{key}",
                "licenseStatus": "unknown",
                "bodyStatus": "available",
                "segments": [
                    {
                        "id": f"seg-{key}",
                        "locator": "synthetic:p[1]",
                        "text": text,
                        "mentions": [],
                    }
                ],
            }
        )
        batch["evidence"].append(
            {
                "id": evidence_id,
                "documentId": f"doc-{key}",
                "documentVersion": f"synthetic-version-{key}",
                "extractionVersion": f"synthetic-extraction-{key}",
                "segmentId": f"seg-{key}",
                "start": 0,
                "end": len(text),
            }
        )

    if extra_rule is None:
        add(
            "president",
            "official-president-status",
            "briefing-XvTXtZbh",
            PRESIDENT_URL,
            "합성 대통령 직위 문장",
            "합성인 대통령 [테스트 전용 문장]",
            {
                "id": "person-president-fixture",
                "kind": "person",
                "name": "합성인",
                "identifiers": [
                    {"namespace": "KR_OFFICE_PROFILE_CANDIDATE", "value": "synthetic"}
                ],
            },
        )
    clauses = {
        "neac-chair": "대통령(의장)",
        "pacst-chair": "대통령(의장)",
        "puac-chair": "[ 의장 : 대통령 ]",
        "nsc-chair": "② 대통령은 회의의 의장이 된다.",
    }
    for rule in [extra_rule] if extra_rule else ["neac-chair", "pacst-chair"]:
        url, name, number = RULES[f"official-exofficio-rule:{rule}"]
        add(
            rule,
            "official-exofficio-rule",
            rule,
            url,
            f"합성 {name} 규칙 문장",
            clauses[rule],
            {
                "id": f"org-fixture-{rule}",
                "kind": "organization",
                "name": name,
                "identifiers": [
                    {"namespace": "MOIS_GOVERNMENT_ORGANIZATION", "value": number}
                ],
            },
        )
    return batch
