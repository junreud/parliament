"""Local review validation and explicitly authenticated draft-batch import."""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from parliament_worker.http import validate_official_url
from parliament_worker.knowledge.identifiers import validate_identifiers
from parliament_worker.publish import BackendPublisher

ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,128}")
RELATION_TYPES = {
    "lead_sponsor",
    "co_sponsor",
    "speaker",
    "voter",
    "scheduled_participant",
    "publisher",
    "implementing_agency",
    "committee_proposer",
    "incorporated_into_alternative",
    "concerns",
    "records",
}


def _id(value: Any) -> str:
    """Validate bounded identifiers before reference or storage lookups."""
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise ValueError("invalid identity")
    return value


def _decision(value: Any) -> None:
    """Keep review decisions explicit; truthiness is never an approval signal."""
    if value not in {"pending", "approved", "rejected"}:
        raise ValueError("invalid review decision")


def _offset(start: Any, end: Any, text: str) -> None:
    """Validate Unicode code point ranges, including astral characters."""
    if (
        type(start) is not int
        or type(end) is not int
        or not 0 <= start < end <= len(text)
    ):
        raise ValueError("invalid evidence or mention offset")


def read_batch(path: Path) -> dict[str, Any]:
    """Read a bounded local batch; administrator evidence never appears in logs."""
    if path.stat().st_size > 10_000_000:
        raise ValueError("batch size exceeds limit")
    batch = json.loads(path.read_text(encoding="utf-8"))
    validate_batch(batch)
    return batch


def validate_batch(batch: dict[str, Any]) -> None:
    """Validate evidence referential integrity before review or import.

    Args:
        batch: Explicitly prepared or operator-edited candidate batch.

    Raises:
        ValueError: Identity, role, range or immutable evidence references disagree.
    """
    _id(batch.get("id"))
    _id(batch.get("issueId"))
    arrays = (
        "entities",
        "documents",
        "evidence",
        "relations",
        "activities",
        "contexts",
    )
    if any(
        not isinstance(batch.get(name), list) or len(batch[name]) > 2000
        for name in arrays
    ):
        raise ValueError("invalid batch array")
    entities = {}
    for entity in batch["entities"]:
        validate_identifiers(entity.get("identifiers", []))
        identifier = _id(entity.get("id"))
        if identifier in entities or entity.get("kind") not in {
            "person",
            "organization",
            "bill",
            "policy",
        }:
            raise ValueError("duplicate or invalid entity")
        entities[identifier] = entity
    issue_policy_id = batch.get("issuePolicyId")
    if issue_policy_id is not None and (
        not isinstance(issue_policy_id, str)
        or issue_policy_id not in entities
        or entities[issue_policy_id]["kind"] != "policy"
    ):
        raise ValueError("invalid issue policy identity")
    document_keys, segments, mentions = set(), {}, set()
    for document in batch["documents"]:
        key = (
            _id(document.get("id")),
            _id(document.get("version")),
            _id(document.get("extractionVersion")),
        )
        if key in document_keys:
            raise ValueError("duplicate document version")
        document_keys.add(key)
        validate_official_url(document["sourceUrl"])
        raw_key = document.get("rawStorageKey", "")
        if (
            not isinstance(raw_key, str)
            or raw_key.startswith("/")
            or ".." in raw_key.split("/")
        ):
            raise ValueError("invalid raw storage key")
        for segment in document.get("segments", []):
            segment_key = key + (_id(segment.get("id")),)
            text = segment.get("text")
            if (
                segment_key in segments
                or not isinstance(text, str)
                or len(text) > 2_000_000
            ):
                raise ValueError("invalid segment")
            segments[segment_key] = text
            for mention in segment.get("mentions", []):
                mention_id = _id(mention.get("id"))
                if mention_id in mentions:
                    raise ValueError("duplicate mention identity")
                mentions.add(mention_id)
                _offset(mention.get("start"), mention.get("end"), text)
                if text[mention["start"] : mention["end"]] != mention.get("surface"):
                    raise ValueError("mention surface offset mismatch")
                _decision(mention.get("decision"))
                for person_id in mention.get("candidatePersonIds", []):
                    if entities.get(person_id, {}).get("kind") != "person":
                        raise ValueError("invalid person candidate")
                person_id = mention.get("personId")
                if (
                    mention["decision"] == "approved"
                    and entities.get(person_id, {}).get("kind") != "person"
                ):
                    raise ValueError("approved mention requires verified person")
    evidence = {}
    for item in batch["evidence"]:
        evidence_id = _id(item.get("id"))
        key = (
            item.get("documentId"),
            item.get("documentVersion"),
            item.get("extractionVersion"),
            item.get("segmentId"),
        )
        if evidence_id in evidence or key not in segments:
            raise ValueError("invalid evidence reference")
        _offset(item.get("start"), item.get("end"), segments[key])
        evidence[evidence_id] = item
    event_ids = {_id(item.get("id")) for item in batch["activities"]}
    targets = set(entities) | event_ids | {key[0] for key in document_keys}
    relation_ids = set()
    for relation in batch["relations"]:
        relation_id = _id(relation.get("id"))
        if (
            relation_id in relation_ids
            or relation.get("type") not in RELATION_TYPES
            or relation.get("subjectId") not in targets
            or relation.get("objectId") not in targets
        ):
            raise ValueError("invalid relation")
        relation_ids.add(relation_id)
        _decision(relation.get("decision"))
        citations = relation.get("evidenceIds", [])
        if any(identifier not in evidence for identifier in citations):
            raise ValueError("relation evidence missing")
        if relation["decision"] == "approved" and (
            not citations or not str(relation.get("reason", "")).strip()
        ):
            raise ValueError("approved relation requires evidence and reason")
    for entity in batch["entities"]:
        for fact in [*entity.get("facts", []), *entity.get("tenures", [])]:
            if not fact.get("evidenceIds") or any(
                identifier not in evidence for identifier in fact["evidenceIds"]
            ):
                raise ValueError("entity fact requires evidence")
    for context in batch["contexts"]:
        if context.get("scheduledPrecision", "unknown") not in {
            "date",
            "second",
            "unknown",
        }:
            raise ValueError("invalid scheduled precision")
        scheduled_at = context.get("scheduledAt")
        if scheduled_at is not None:
            try:
                scheduled = datetime.fromisoformat(scheduled_at)
            except (ValueError, TypeError) as error:
                raise ValueError("invalid scheduled time") from error
            if scheduled.tzinfo is None:
                raise ValueError("scheduled time requires a timezone")
        if (
            context.get("eventId") not in event_ids
            or any(
                identifier not in relation_ids
                for identifier in context.get("relationIds", [])
            )
            or any(
                identifier not in evidence
                for identifier in context.get("evidenceIds", [])
            )
        ):
            raise ValueError("invalid activity context")


def review_export(batch: dict[str, Any]) -> dict[str, Any]:
    """Create a reviewable copy while preserving every unapproved candidate."""
    validate_batch(batch)
    return json.loads(json.dumps(batch, ensure_ascii=False))


class KnowledgePublisher(BackendPublisher):
    """Use the existing fixed backend/auth boundary for candidate batches only."""

    def __init__(
        self,
        base_url: str,
        admin_key: str,
        *,
        enabled: bool = False,
        client: httpx.Client | None = None,
    ) -> None:
        super().__init__(base_url, admin_key, enabled=enabled, client=client)
        self.endpoint = base_url.rstrip("/") + "/admin/tracking/knowledge/batches"

    @classmethod
    def from_env(cls) -> "KnowledgePublisher":
        """Read credentials from environment; imported batches remain drafts."""
        key = os.environ.get("TRACKING_ADMIN_KEY") or os.environ.get(
            "PARLIAMENT_INGESTION_ADMIN_KEY", ""
        )
        return cls(
            os.environ.get("PARLIAMENT_BACKEND_URL", "http://127.0.0.1:8080"),
            key,
            enabled=True,
        )

    def import_batch(self, batch: dict[str, Any]) -> dict[str, Any]:
        """Import a validated candidate without requesting public approval."""
        validate_batch(batch)
        response = self.client.post(
            self.endpoint,
            json=batch,
            headers={"X-Parliament-Ingestion-Key": self._admin_key},
            follow_redirects=False,
        )
        if response.is_redirect:
            raise ValueError("backend auth redirect refused")
        response.raise_for_status()
        return response.json()
