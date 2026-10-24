"""Build pending review candidates from selected, actually extracted source spans."""

import argparse
import copy
import logging
import re
from pathlib import Path
from typing import Any

from parliament_worker.knowledge.extract import digest
from parliament_worker.knowledge.review import read_batch, validate_batch
from parliament_worker.knowledge.store import private_write

LOGGER = logging.getLogger(__name__)
ORIGINAL_BILLS = (
    2200703,
    2200987,
    2201497,
    2201227,
    2201707,
    2202484,
    2203287,
    2203461,
)


def enrich(batch: dict[str, Any]) -> dict[str, Any]:
    """Prepare cited candidates without approving identities, roles or reuse.

    Args:
        batch: A collected and extracted child-support candidate batch.

    Returns:
        A separate immutable candidate version with source-backed lineage hints.
    """
    if batch.get("issueId") != "child-support-advance":
        raise ValueError("this packet is only for the selected child-support pilot")
    result = copy.deepcopy(batch)
    entities = {item["id"]: item for item in result["entities"]}
    if entities.get("policy-child-support-advance", {}).get("kind") == "policy":
        result["issuePolicyId"] = "policy-child-support-advance"
    documents = {item["id"]: item for item in result["documents"]}
    evidence = {
        (item["documentId"], item["segmentId"]): item for item in result["evidence"]
    }
    relations = {item["id"]: item for item in result["relations"]}

    def candidate(subject: str, target: str, kind: str, citation: str) -> str:
        identifier = "relation_" + digest([subject, target, kind, citation])
        relations.setdefault(
            identifier,
            {
                "id": identifier,
                "subjectId": subject,
                "objectId": target,
                "type": kind,
                "evidenceIds": [citation],
                "decision": "pending",
                "reason": "원문 구간을 확인하고 관계의 의미·인물 신원을 별도로 검수해야 합니다.",
            },
        )
        return identifier

    alternative = documents.get("doc-alternative-2204313-pdf", {})
    for number in ORIGINAL_BILLS:
        if f"bill-{number}" not in entities or "bill-2204313" not in entities:
            continue
        for segment in alternative.get("segments", []):
            citation = evidence.get((alternative["id"], segment["id"]))
            if citation and re.search(rf"(?<!\d){number}(?!\d)", segment["text"]):
                candidate(
                    f"bill-{number}",
                    "bill-2204313",
                    "incorporated_into_alternative",
                    citation["id"],
                )
                break

    for number, person in (
        (2201707, "person-kim-miae"),
        (2200703, "person-kim-namhee"),
    ):
        document = documents.get(f"doc-bill-{number}", {})
        entity = entities.get(person)
        if not entity or f"bill-{number}" not in entities:
            continue
        for segment in document.get("segments", []):
            citation = evidence.get((document["id"], segment["id"]))
            if (
                citation
                and "발의정보" in segment["text"]
                and entity["name"] in segment["text"]
                and str(number) in segment["text"]
            ):
                candidate(person, f"bill-{number}", "lead_sponsor", citation["id"])
                break

    release = documents.get("doc-child-support-followup")
    if (
        release
        and release.get("publishedAt")
        and release.get("bodyStatus") in {"available", "partial"}
    ):
        cited = [
            evidence[(release["id"], segment["id"])]
            for segment in release["segments"]
            if (release["id"], segment["id"]) in evidence
        ]
        if cited:
            scheduled = any(
                re.search(r"개최\s*한다|예정", segment["text"])
                for segment in release["segments"]
            )
            event_id = "announcement_" + digest(
                [release["sourceKey"], release["recordKey"]]
            )
            event_version = "v_" + digest(
                [release["version"], release["extractionVersion"]]
            )
            activity = {
                "id": event_id,
                "version": event_version,
                "type": "announcement",
                "title": release["title"],
                "summary": None,
                "stage": "scheduled" if scheduled else "announced",
                "personIds": [],
                "topics": ["child-support-advance", "family"],
                "billId": None,
                "occurredAt": None,
                "publishedAt": release["publishedAt"],
                "collectedAt": release["collectedAt"],
                "sourceUrl": release["sourceUrl"],
                "evidence": [
                    {
                        "id": item["id"],
                        "sourceUrl": release["sourceUrl"],
                        "sourceVersion": release["version"],
                        "locator": segment["locator"],
                        "excerpt": segment["text"],
                    }
                    for segment, item in (
                        (segment, evidence[(release["id"], segment["id"])])
                        for segment in release["segments"]
                        if (release["id"], segment["id"]) in evidence
                    )
                ],
                "votes": [],
                "corrected": False,
                "coverage": "운영자 선정 정부 발표의 검수 후보. 개최 결과·정책 효과는 별도 확인 대상입니다. 원문 게시일은 날짜 단위입니다.",
            }
            event_relations = []
            if "org-gender-family" in entities:
                event_relations.append(
                    candidate(
                        "org-gender-family", event_id, "publisher", cited[0]["id"]
                    )
                )
            for segment in release["segments"]:
                citation = evidence.get((release["id"], segment["id"]))
                if (
                    scheduled
                    and citation
                    and "원민경" in segment["text"]
                    and "주재" in segment["text"]
                    and "person-won-minkyung" in entities
                ):
                    event_relations.append(
                        candidate(
                            "person-won-minkyung",
                            event_id,
                            "scheduled_participant",
                            citation["id"],
                        )
                    )
                    break
            result["activities"] = [
                a for a in result["activities"] if a["id"] != event_id
            ] + [activity]
            result["contexts"] = [
                c for c in result["contexts"] if c["eventId"] != event_id
            ] + [
                {
                    "eventId": event_id,
                    "eventVersion": event_version,
                    "changeKind": "new_record",
                    "relationIds": event_relations,
                    "evidenceIds": [item["id"] for item in cited],
                    "documentIds": [release["id"]],
                }
            ]
    result["relations"] = list(relations.values())
    stable = {key: value for key, value in result.items() if key != "id"}
    stable["documents"] = [
        {
            key: value
            for key, value in item.items()
            if key not in {"observationId", "observedAt"}
        }
        for item in result["documents"]
    ]
    result["id"] = "batch_" + digest(stable)
    return result


def main() -> None:
    """Save a private pending packet; never import or publish it implicitly."""
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = enrich(read_batch(args.batch))
    validate_batch(result)
    private_write(
        args.output,
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2).encode(),
    )
    logging.basicConfig(level=logging.INFO)
    LOGGER.info(
        "Prepared %s pending relations; human review and publication remain separate",
        len(result["relations"]),
    )


if __name__ == "__main__":
    main()
