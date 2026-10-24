"""Continuous bounded inference execution with durable recovery and revisions."""

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from parliament_worker.graphrag.claim_selection import (
    CLAIM_SELECTION_CONTRACT,
    SOURCE_GROUP_SELECTION_CONTRACT,
    materialize_selection,
)
from parliament_worker.graphrag.client import (
    InferenceClient,
    parse_completion,
)
from parliament_worker.graphrag.community_enrichment import (
    SELECTION_CONTRACT,
    materialize_evidence_selection,
)
from parliament_worker.graphrag.community_retry import materialize_partition
from parliament_worker.graphrag.execution import execute_tick
from parliament_worker.graphrag.index import (
    children_current,
    dependencies_current,
    reconcile,
    routing_current,
)
from parliament_worker.graphrag.inputs import read_sources
from parliament_worker.graphrag.office_repair import (
    TYPED_LIST_REPAIR_VERSION,
    validate_composite_source_proof,
    validate_typed_list_source_proof,
)
from parliament_worker.graphrag.output_contract import (
    ANSWER_CONTRACT,
    ASSIGNMENT_COMMUNITY_CONTRACT,
    COMPACT_CONTRACT,
    DIRECTIONAL_CONTRACT,
    LEGACY_ANSWER_CONTRACT,
    materialize_answer,
    materialize_compact_extraction,
)
from parliament_worker.graphrag.policy import apply_review_policy
from parliament_worker.graphrag.prompts import (
    PROMPT_VERSION,
    prune_invalid_graph_edges,
    validate_extraction,
    validate_report,
)
from parliament_worker.graphrag.query import validate_answer
from parliament_worker.graphrag.relation_completion import materialize_relation
from parliament_worker.graphrag.store import GraphStore
from parliament_worker.graphrag.store_bulk import stored_artifact_versions
from parliament_worker.graphrag.store_schema import content_digest

LOGGER = logging.getLogger(__name__)


class Factory:
    """Plan only changed inputs and execute already persisted inference intentions.

    Args:
        store: Private version/job/artifact repository.
        client: Remote async inference transport without automatic retries.
        model_signature: Actual repository and pinned revision separated by @.
        concurrency: Maximum HTTP workers and unfinished requests (1..64).
        daily_jobs: UTC-day new-request limit; zero disables the daily limit.
        daily_tokens: Reserved token limit; zero disables the daily limit.
    """

    def __init__(
        self,
        store: GraphStore,
        client: InferenceClient,
        model_signature: str,
        *,
        concurrency: int = 1,
        daily_jobs: int = 500,
        daily_tokens: int = 2_000_000,
        queue_capacity: int = 256,
        poll_seconds: float = 3.0,
        retry_output_failures: bool = False,
    ) -> None:
        if (
            not 1 <= concurrency <= 64
            or not 0 <= daily_jobs <= 100_000
            or daily_tokens != 0
            and daily_tokens < 4096
            or not 1 <= queue_capacity <= 2000
            or not 0.1 <= poll_seconds <= 60
        ):
            raise ValueError("invalid GraphRAG execution limits")
        if (
            not isinstance(model_signature, str)
            or "@" not in model_signature
            or len(model_signature) > 512
        ):
            raise ValueError("actual model and revision must be pinned")
        self.store, self.client, self.model_signature = store, client, model_signature
        self.concurrency, self.daily_jobs, self.daily_tokens = (
            concurrency,
            daily_jobs,
            daily_tokens,
        )
        self.queue_capacity, self.poll_seconds = queue_capacity, poll_seconds
        self.owner = "worker_" + uuid4().hex
        self.retry_output_failures = retry_output_failures
        self._last_office_repair_scan = 0.0
        self._projections_recovered = False
        self.office_inputs: list[Path] | None = None

    def sync_inputs(
        self, paths: list[Path], *, retire_missing: bool = False
    ) -> dict[str, int]:
        """Scan all configured inputs before applying changes or withdrawals."""
        sources = read_sources(paths)
        self.office_inputs = list(paths)
        known = {
            source["scope"]: source
            for source in self.store.sources(active_only=False, include_payload=False)
        }
        changes = [
            source
            for source in sources
            if source["scope"] not in known
            or not known[source["scope"]]["active"]
            or known[source["scope"]]["fingerprint"] != source["fingerprint"]
        ]
        changed = self.store.put_sources(changes) if changes else 0
        changed_scopes = {source["scope"] for source in changes}
        current_observations = self.store.source_observation_times()
        reobserved = [
            source
            for source in sources
            if source["scope"] not in changed_scopes
            and source["observedAt"]
            and source["observedAt"] > current_observations.get(source["scope"], "")
        ]
        if reobserved:
            self.store.record_source_observations(reobserved)
        retired = 0
        if retire_missing:
            present = {source["scope"] for source in sources}
            for scope, source in known.items():
                if source["active"] and scope not in present:
                    retired += self.store.retire_source(scope)
        if changed or retired:
            self._last_office_repair_scan = 0.0
        return {
            "changed": changed,
            "retired": retired,
            "invalidated": reconcile(self.store),
        }

    def plan(self) -> dict[str, int]:
        """Recover prior work, then extract sources before derived reports."""
        from parliament_worker.graphrag.factory_plan import plan_factory

        return plan_factory(self)

    def _paused(self) -> bool:
        return self.store.get_artifact("control", "pause") is not None

    def resume(self) -> None:
        """Clear an operator pause after credentials/model configuration is corrected."""
        self.store.invalidate_artifact("control", "pause")

    def _reservation(
        self, job: dict[str, Any], now: float, jobs: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        metadata = dict(job["metadata"])
        if metadata.get("submitted_day"):
            return metadata
        day = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
        submitted = [
            work for work in jobs if work["metadata"].get("submitted_day") == day
        ]
        tokens = (
            sum(
                len(message["content"].encode())
                for message in job["request"]["messages"]
            )
            + job["request"].get("max_completion_tokens", 768)
            + 256
        )
        if (
            self.daily_jobs
            and len(submitted) >= self.daily_jobs
            or self.daily_tokens
            and sum(work["metadata"].get("reserved_tokens", 0) for work in submitted)
            + tokens
            > self.daily_tokens
        ):
            return None
        return {
            **metadata,
            "submitted_day": day,
            "reserved_tokens": tokens,
            "expected_model": self.model_signature,
        }

    def _model_matches(self, metadata: dict[str, Any]) -> bool:
        actual, revision = self.model_signature.rsplit("@", 1)
        return (
            metadata.get("actual_model") == actual
            and metadata.get("revision") == revision
        )

    def _complete(
        self, job: dict[str, Any], response: dict[str, Any], now: float
    ) -> None:
        metadata = {**job["metadata"], **response.get("_modelMetadata", {})}
        if not self._model_matches(metadata):
            self.store.release(
                job["id"],
                self.owner,
                state="failed",
                error="model_revision_mismatch",
                remote_id=response.get("request_id") or job["remote_id"],
                metadata=metadata,
            )
            self.store.put_artifact(
                "control", "pause", {}, {"reason": "model_revision_mismatch", "at": now}
            )
            return
        output = parse_completion(response)
        context = job["context"]
        sources = {
            source["scope"]: source
            for source in self.store.sources(include_payload=False)
        }
        if (
            not dependencies_current(context, sources)
            or not routing_current(job["kind"], context)
            or not children_current(self.store, context)
        ):
            self.store.release(job["id"], self.owner, state="obsolete")
            return
        if context.get("output_contract") == SELECTION_CONTRACT:
            previous = self.store.get_artifact("community", context["artifact_key"])
            if not previous or previous["version"] != context["prior_report_version"]:
                self.store.release(job["id"], self.owner, state="obsolete")
                return
        if job["kind"] == "extract":
            relation = materialize_relation(self.store, output, context)
            if relation is not None:
                result = relation
            else:
                if context.get("repair_version") == TYPED_LIST_REPAIR_VERSION:
                    scope = context["sources"][0]["scope"]
                    source = next(
                        (
                            item
                            for item in self.store.sources()
                            if item["scope"] == scope
                        ),
                        None,
                    )
                    if source is None:
                        raise ValueError("typed list source proof missing source")
                    validate_typed_list_source_proof(context, source)
                if any("sourceUnitIds" in unit for unit in context["units"].values()):
                    scope = context["sources"][0]["scope"]
                    source = next(
                        (
                            item
                            for item in self.store.sources()
                            if item["scope"] == scope
                        ),
                        None,
                    )
                    if source is None:
                        raise ValueError("composite source proof missing source")
                    validate_composite_source_proof(context, source)
                if context.get("output_contract") in {
                    COMPACT_CONTRACT,
                    DIRECTIONAL_CONTRACT,
                }:
                    output = materialize_compact_extraction(output, context)
                result = apply_review_policy(validate_extraction(output, context))
        elif job["kind"] == "community":
            if context.get("output_contract") == SELECTION_CONTRACT:
                result = materialize_evidence_selection(output, context)
            else:
                if context.get("output_contract") == ASSIGNMENT_COMMUNITY_CONTRACT:
                    output = materialize_partition(output, context)
                result = validate_report(output, context)
            if context.get("output_contract") == ASSIGNMENT_COMMUNITY_CONTRACT:
                result["reportStatus"] = "membership_only"
                for group in result["groups"]:
                    group["reportStatus"] = "membership_only"
        elif job["kind"] in {"query_local", "query_map", "query_reduce"}:
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
        else:
            raise ValueError("unknown graph task")
        usage = response.get("result", {}).get("usage", {})
        if isinstance(usage, dict):
            metadata["usage"] = {
                key: value
                for key, value in usage.items()
                if key in {"prompt_tokens", "completion_tokens", "total_tokens"}
                and type(value) is int
                and value >= 0
            }
        # Persist completion first. A crash before projection is replayable locally,
        # and never resubmits the already completed remote request.
        self.store.release(
            job["id"],
            self.owner,
            state="completed",
            result=result,
            remote_id=response.get("request_id") or job["remote_id"],
            metadata=metadata,
            error=None,
        )
        self.project(self.store.get_job(job["id"]))
        if job["kind"] == "extract" and not context.get("repair_version"):
            self._last_office_repair_scan = 0.0

    def project(self, job: dict[str, Any]) -> None:
        """Idempotently project a completed task after a crash or normal completion."""
        context = job["context"]
        if (
            context.get("model_signature") != self.model_signature
            or context.get("prompt_version", PROMPT_VERSION) != PROMPT_VERSION
        ):
            return
        sources = {
            source["scope"]: source
            for source in self.store.sources(include_payload=False)
        }
        if (
            not dependencies_current(context, sources)
            or not routing_current(job["kind"], context)
            or not children_current(self.store, context)
        ):
            return
        kind = (
            "graph"
            if job["kind"] == "extract"
            else (
                "community"
                if job["kind"] == "community"
                else "answer_map" if job["kind"] == "query_map" else "answer"
            )
        )
        dependency = {
            key: context[key]
            for key in (
                "sources",
                "source_manifest",
                "children",
                "model_signature",
                "prompt_version",
                "routing_version",
                "group_id_version",
                "snapshot",
            )
            if key in context
        }
        current = self.store.get_artifact(kind, context["artifact_key"])
        prior_report_version = context.get("quality_repair_for_version")
        if prior_report_version and (
            current is None or current["version"] != prior_report_version
        ):
            return
        payload = (
            prune_invalid_graph_edges(job["result"])
            if kind == "graph"
            else job["result"]
        )
        if (
            current
            and current["dependency"] == dependency
            and current["payload"] == payload
        ):
            return
        if context.get("output_contract") == SELECTION_CONTRACT and (
            current is None or current["version"] != context["prior_report_version"]
        ):
            return
        self.store.put_artifact(kind, context["artifact_key"], dependency, payload)

    def recover_projections(self, *, reactivate_cached: bool = False) -> None:
        """Recover unsaved results and reactivate cached revisions on model return."""
        sources = {
            source["scope"]: source
            for source in self.store.sources(include_payload=False)
        }
        saved_versions = stored_artifact_versions(self.store)
        candidates = {}
        for job in self.store.jobs():
            context = job["context"]
            if (
                job["state"] != "completed"
                or job["result"] is None
                or context.get("model_signature") != self.model_signature
                or context.get("prompt_version", PROMPT_VERSION) != PROMPT_VERSION
                or not isinstance(context.get("artifact_key"), str)
                or not routing_current(job["kind"], context)
            ):
                continue
            kind = (
                "graph"
                if job["kind"] == "extract"
                else (
                    "community"
                    if job["kind"] == "community"
                    else "answer_map" if job["kind"] == "query_map" else "answer"
                )
            )
            candidates[(kind, context["artifact_key"])] = job
        recovered = 0
        for (kind, key), job in candidates.items():
            context = job["context"]
            if not dependencies_current(context, sources):
                continue
            dependency = {
                key: context[key]
                for key in (
                    "sources",
                    "source_manifest",
                    "children",
                    "model_signature",
                    "prompt_version",
                    "routing_version",
                    "group_id_version",
                    "snapshot",
                )
                if key in context
            }
            payload = (
                prune_invalid_graph_edges(job["result"])
                if kind == "graph"
                else job["result"]
            )
            version = content_digest([kind, key, dependency, payload])
            if (kind, key, version) in saved_versions and not reactivate_cached:
                continue
            if not children_current(self.store, context):
                continue
            self.project(job)
            saved_versions.add((kind, key, version))
            recovered += 1
        if recovered:
            LOGGER.info("GraphRAG recovered unsaved projections=%s", recovered)
        self._projections_recovered = True

    def tick(self, max_operations: int = 4) -> int:
        """Execute persisted submit/poll operations with bounded HTTP concurrency."""
        return execute_tick(self, max_operations)
