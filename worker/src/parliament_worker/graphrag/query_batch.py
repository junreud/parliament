"""Validate and atomically save a wave of grounded query-map completions."""

import time
from typing import TYPE_CHECKING, Any

from parliament_worker.graphrag.claim_selection import (
    CLAIM_SELECTION_CONTRACT,
    SOURCE_GROUP_SELECTION_CONTRACT,
    materialize_selection,
)
from parliament_worker.graphrag.client import parse_completion
from parliament_worker.graphrag.index import (
    children_current,
    dependencies_current,
    routing_current,
)
from parliament_worker.graphrag.job_codec import encode_job
from parliament_worker.graphrag.output_contract import (
    ANSWER_CONTRACT,
    LEGACY_ANSWER_CONTRACT,
    materialize_answer,
)
from parliament_worker.graphrag.query import validate_answer
from parliament_worker.graphrag.store_schema import (
    canonical_json,
    content_digest,
    require_lease,
    updated_job,
)

if TYPE_CHECKING:
    from parliament_worker.graphrag.engine import Factory


_DEPENDENCY_FIELDS = (
    "sources",
    "source_manifest",
    "children",
    "model_signature",
    "prompt_version",
    "routing_version",
    "snapshot",
)


def _save_validated(factory: "Factory", prepared: list[dict[str, Any]]) -> None:
    """Commit all validated results and their immutable artifacts together."""
    instant = time.time()
    with factory.store._transaction() as db:
        sources = {
            row["scope"]: dict(row)
            for row in db.execute(
                "SELECT scope,fingerprint,generation FROM sources WHERE active=1"
            )
        }
        if any(
            not dependencies_current(item["job"]["context"], sources)
            for item in prepared
        ):
            raise ValueError("query source changed before completion")
        for item in prepared:
            original = item["job"]
            job = require_lease(
                factory.store._read_job(db, original["id"]), factory.owner, instant
            )
            if job["kind"] != "query_map":
                raise ValueError("only query maps may use batch completion")
            updated = updated_job(
                job,
                {
                    "state": "completed",
                    "result": item["result"],
                    "remote_id": item["remote_id"],
                    "metadata": item["metadata"],
                    "error": None,
                },
                instant,
            )
            updated.update(lease_owner=None, lease_until=0.0)
            db.execute(
                "UPDATE jobs SET data=? WHERE id=?",
                (encode_job(updated), job["id"]),
            )
            context = job["context"]
            key = context["artifact_key"]
            dependency = {
                field: context[field]
                for field in _DEPENDENCY_FIELDS
                if field in context
            }
            payload = item["result"]
            version = content_digest(["answer_map", key, dependency, payload])
            previous = db.execute(
                "SELECT dependency,payload FROM artifacts WHERE kind=? "
                "AND artifact_key=? AND version=?",
                ("answer_map", key, version),
            ).fetchone()
            if previous and (
                previous["dependency"] != canonical_json(dependency)
                or previous["payload"] != canonical_json(payload)
            ):
                raise ValueError("immutable artifact version conflict")
            db.execute(
                "UPDATE artifacts SET current=0 WHERE kind=? AND artifact_key=?",
                ("answer_map", key),
            )
            db.execute(
                "INSERT INTO artifacts(kind,artifact_key,version,dependency,payload,current) "
                "VALUES(?,?,?,?,?,1) ON CONFLICT(kind,artifact_key,version) "
                "DO UPDATE SET current=1",
                (
                    "answer_map",
                    key,
                    version,
                    canonical_json(dependency),
                    canonical_json(payload),
                ),
            )


def commit_query_maps(
    factory: "Factory", completed: list[tuple[dict[str, Any], dict[str, Any]]]
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Batch valid maps; return other results to the ordinary recovery path.

    Args:
        factory: Current single-owner inference worker.
        completed: Persisted remote completion receipts for this HTTP wave.

    Returns:
        Responses requiring normal individual completion or failure handling.
    """
    if not any(job["kind"] == "query_map" for job, _ in completed):
        return completed
    sources = {
        source["scope"]: source
        for source in factory.store.sources(include_payload=False)
    }
    prepared: list[dict[str, Any]] = []
    ordinary: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for job, response in completed:
        if job["kind"] != "query_map":
            ordinary.append((job, response))
            continue
        context = job["context"]
        try:
            metadata = {**job["metadata"], **response.get("_modelMetadata", {})}
            if (
                not factory._model_matches(metadata)
                or not dependencies_current(context, sources)
                or not routing_current(job["kind"], context)
                or not children_current(factory.store, context)
            ):
                ordinary.append((job, response))
                continue
            output = parse_completion(response)
            if context.get("output_contract") in {
                CLAIM_SELECTION_CONTRACT,
                SOURCE_GROUP_SELECTION_CONTRACT,
            }:
                result = materialize_selection(output, context)
            elif context.get("output_contract") in {
                ANSWER_CONTRACT,
                LEGACY_ANSWER_CONTRACT,
            }:
                output = materialize_answer(output, context)
                result = validate_answer(output, context)
            else:
                result = validate_answer(output, context)
        except (ValueError, TypeError, AttributeError, KeyError):
            ordinary.append((job, response))
            continue
        completion = response.get("result")
        usage = completion.get("usage", {}) if isinstance(completion, dict) else {}
        if isinstance(usage, dict):
            metadata["usage"] = {
                key: value
                for key, value in usage.items()
                if key in {"prompt_tokens", "completion_tokens", "total_tokens"}
                and type(value) is int
                and value >= 0
            }
        prepared.append(
            {
                "job": job,
                "result": result,
                "remote_id": response.get("request_id") or job["remote_id"],
                "metadata": metadata,
            }
        )
    if prepared:
        try:
            _save_validated(factory, prepared)
        except ValueError as error:
            if str(error) not in {
                "stale graph job lease",
                "pilot store busy",
                "query source changed before completion",
            }:
                raise
            ids = {item["job"]["id"] for item in prepared}
            ordinary.extend(
                (job, response) for job, response in completed if job["id"] in ids
            )
    return ordinary
