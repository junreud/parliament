"""Parallel HTTP, with durable reservations and one coordinator for state writes."""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Any

from parliament_worker.graphrag import query_batch
from parliament_worker.graphrag.client import InferenceError
from parliament_worker.graphrag.index import dependencies_current
from parliament_worker.graphrag.prompts import PROMPT_VERSION
from parliament_worker.graphrag.receipts import save_receipts
from parliament_worker.graphrag.recovery import pause_unknown_acceptance

if TYPE_CHECKING:
    from parliament_worker.graphrag.engine import Factory

LOGGER = logging.getLogger(__name__)
WAVE_LEASE_SECONDS = 600
RESULT_BATCH_SIZE = 16
VALIDATION_REASON_CODES = {
    "community membership coverage incomplete": "community_membership_incomplete",
    "graph quote is absent or ambiguous": "graph_quote_absent_or_ambiguous",
    "self relation is unsupported": "self_relation_unsupported",
    "invalid graph relation": "invalid_graph_relation",
    "invalid relation endpoints": "invalid_relation_endpoints",
    "unknown or duplicate community member": "unknown_or_duplicate_community_member",
}


class _RemoteWave:
    """Count actual overlapping HTTP calls without giving workers store access."""

    def __init__(self, factory: "Factory") -> None:
        self.client = factory.client
        self.lock = threading.Lock()
        self.active = self.peak = 0
        self.submits = self.polls = 0
        self.submit_seconds = self.poll_seconds = 0.0

    def call(self, job: dict[str, Any]) -> dict[str, Any]:
        """Submit or poll the exact persisted request through the shared client."""
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        started = time.monotonic()
        try:
            if job["remote_id"]:
                return self.client.poll(job["remote_id"])
            return self.client.submit(job["request"], job["idempotency_key"])
        finally:
            with self.lock:
                self.active -= 1
                elapsed = time.monotonic() - started
                if job["remote_id"]:
                    self.polls += 1
                    self.poll_seconds += elapsed
                else:
                    self.submits += 1
                    self.submit_seconds += elapsed


def _checkpoint_before_http(
    factory: "Factory", changes: list[tuple[str, dict[str, Any], bool]]
) -> bool:
    """Discard a wave whose lease expired before any remote request began."""
    try:
        factory.store.update_leased(factory.owner, changes)
    except ValueError as error:
        if str(error) != "stale graph job lease":
            raise
        LOGGER.warning("GraphRAG pre-HTTP lease expired; wave will be reclaimed")
        return False
    return True


def _remote_slot_held(job: dict[str, Any]) -> bool:
    """Count only accepted or uncertain remote work against concurrency."""
    return job["state"] in {"submitting", "polling", "deferred"} and bool(
        job["remote_id"] or job["metadata"].get("completion_uncertain")
    )


def _prepare(factory: "Factory", leased: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reserve a whole wave before HTTP; workers never race budgets or storage."""
    now = time.time()
    uncertain = next(
        (
            job
            for job in leased
            if not job["remote_id"] and job["metadata"].get("completion_uncertain")
        ),
        None,
    )
    if uncertain:
        if not _checkpoint_before_http(
            factory,
            [
                (
                    job["id"],
                    (
                        {
                            "state": "deferred",
                            "next_poll": now + 3600,
                            "error": "inference_acceptance_unknown",
                        }
                        if job["id"] == uncertain["id"]
                        else {}
                    ),
                    True,
                )
                for job in leased
            ],
        ):
            return []
        pause_unknown_acceptance(factory.store, uncertain["id"], now)
        return []
    sources = {
        source["scope"]: source
        for source in factory.store.sources(include_payload=False)
    }
    current = {job["id"]: job for job in factory.store.jobs()}
    running = sum(_remote_slot_held(job) for job in current.values())
    changes, dispatch = [], []
    for job in leased:
        context = job["context"]
        if (
            not dependencies_current(context, sources)
            or context.get("model_signature") != factory.model_signature
            or context.get("prompt_version", PROMPT_VERSION) != PROMPT_VERSION
        ):
            changes.append((job["id"], {"state": "obsolete"}, True))
            if _remote_slot_held(job):
                running -= 1
            continue
        if job["remote_id"]:
            dispatch.append(job)
            continue
        remote_slot_held = _remote_slot_held(job)
        if running >= factory.concurrency and not remote_slot_held:
            changes.append((job["id"], {"next_poll": now + factory.poll_seconds}, True))
            continue
        metadata = factory._reservation(job, now, list(current.values()))
        if metadata is None:
            changes.append(
                (job["id"], {"next_poll": now + 60, "error": "daily_work_limit"}, True)
            )
            continue
        fields = {
            "state": "submitting",
            "metadata": {**metadata, "completion_uncertain": True},
            "attempts": job["attempts"] + 1,
            "next_poll": now,
        }
        changes.append((job["id"], fields, False))
        prepared = {**job, **fields}
        current[job["id"]] = prepared
        dispatch.append(prepared)
        running += not remote_slot_held
    if changes:
        if not _checkpoint_before_http(factory, changes):
            return []
    return dispatch


def _inference_error(
    factory: "Factory", job: dict[str, Any], error: InferenceError
) -> None:
    now = time.time()
    fields = _error_fields(job, error, now)
    factory.store.release(job["id"], factory.owner, **fields)
    if error.uncertain and not job["remote_id"]:
        pause_unknown_acceptance(factory.store, job["id"], now)
    elif error.status in {401, 403, 404, 409}:
        factory.store.put_artifact(
            "control",
            "pause",
            {},
            {
                "reason": "inference_configuration_rejected",
                "status": error.status,
                "at": now,
            },
        )


def _error_fields(
    job: dict[str, Any], error: InferenceError, now: float
) -> dict[str, Any]:
    """Preserve the original remote identity while deferring one failed call."""
    fields: dict[str, Any] = {
        "state": "deferred" if error.retryable else "failed",
        "error": str(error),
        "metadata": {
            **job["metadata"],
            "error_status": error.status,
            "completion_uncertain": error.uncertain,
        },
    }
    if error.retryable:
        delay = max(error.retry_after, min(300, 5 * 2 ** min(job["attempts"], 6)))
        fields["next_poll"] = now + delay
    return fields


def _invalid_content(
    factory: "Factory",
    job: dict[str, Any],
    response: dict[str, Any],
    validation_error: Exception,
) -> None:
    completion = response.get("result")
    choices = completion.get("choices", []) if isinstance(completion, dict) else []
    choice = choices[0] if isinstance(choices, list) and choices else {}
    if isinstance(validation_error, InferenceError):
        failure = str(validation_error)
        reason = (
            "completion_length_exhausted"
            if isinstance(choice, dict) and choice.get("finish_reason") == "length"
            else failure
        )
    else:
        failure = "generated_content_validation_failed"
        reason = VALIDATION_REASON_CODES.get(
            str(validation_error), "other_completion_validation_error"
        )
    factory.store.release(
        job["id"],
        factory.owner,
        state="failed",
        remote_id=response.get("request_id") or job["remote_id"],
        metadata={
            **job["metadata"],
            "validation_reason": reason,
            "completion_uncertain": not bool(
                response.get("request_id") or job["remote_id"]
            ),
        },
        error=failure,
    )
    if isinstance(choice, dict):
        message = choice.get("message", {})
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            factory.store.put_artifact(
                "failure",
                job["id"],
                {},
                {
                    "generated": message["content"][:4096],
                    "reason": failure,
                    "private": True,
                },
            )


def execute_tick(factory: "Factory", max_operations: int) -> int:
    """Run bounded HTTP waves concurrently and save receipts before returning.

    Args:
        factory: Single durable-state coordinator with a thread-safe HTTP client.
        max_operations: Maximum number of claimed jobs, including deferred jobs.

    Returns:
        Number of submit/poll calls returning a decoded response.
    """
    processed, remaining = 0, max_operations
    with ThreadPoolExecutor(
        max_workers=factory.concurrency, thread_name_prefix="graphrag-http"
    ) as pool:
        while remaining > 0 and not factory._paused():
            preparing = time.monotonic()
            leased = factory.store.claim(
                factory.owner,
                lease_seconds=WAVE_LEASE_SECONDS,
                limit=min(remaining, factory.concurrency),
            )
            if not leased:
                break
            remaining -= len(leased)
            dispatch = _prepare(factory, leased)
            started = time.monotonic()
            prepare_seconds = started - preparing
            wave = _RemoteWave(factory)
            futures = {pool.submit(wave.call, job): job for job in dispatch}
            unexpected = None
            responses, errors = [], []
            for future in as_completed(futures):
                job = futures[future]
                try:
                    response = future.result()
                    if response.get("state") not in {
                        "received",
                        "queued",
                        "running",
                        "completed",
                        "failed",
                        "cancelled",
                    }:
                        raise InferenceError(
                            "unrecognized_remote_state", retryable=True, uncertain=True
                        )
                    processed += 1
                    responses.append((job, response))
                except InferenceError as error:
                    errors.append((job, error))
                except Exception as error:
                    unexpected = error
            applying = time.monotonic()
            # Save all observed IDs before any validation/error can pause the factory.
            try:
                completed = save_receipts(factory, responses)
            except ValueError as error:
                if str(error) not in {"stale graph job lease", "pilot store busy"}:
                    raise
                LOGGER.warning("GraphRAG receipt checkpoint deferred: %s", error)
                continue
            completed = query_batch.commit_query_maps(factory, completed)
            if (
                errors
                and not responses
                and all(
                    str(error) == "inference_dns_unavailable"
                    and error.retryable
                    and not error.uncertain
                    for _, error in errors
                )
            ):
                now = time.time()
                try:
                    factory.store.update_leased(
                        factory.owner,
                        [
                            (job["id"], _error_fields(job, error, now), True)
                            for job, error in errors
                        ],
                    )
                except ValueError as error:
                    if str(error) not in {"stale graph job lease", "pilot store busy"}:
                        raise
                    LOGGER.warning("GraphRAG DNS deferral batch retry: %s", error)
                else:
                    errors = []
            outcomes = [("error", job, error) for job, error in errors] + [
                ("completed", job, response) for job, response in completed
            ]
            last_renewal = 0.0
            for index in range(0, len(outcomes), RESULT_BATCH_SIZE):
                now = time.monotonic()
                if index == 0 or now - last_renewal >= WAVE_LEASE_SECONDS / 4:
                    remaining_ids = [item["id"] for _, item, _ in outcomes[index:]]
                    try:
                        factory.store.renew_leases(
                            factory.owner, remaining_ids, WAVE_LEASE_SECONDS
                        )
                    except ValueError as error:
                        if str(error) not in {
                            "stale graph job lease",
                            "pilot store busy",
                        }:
                            raise
                        LOGGER.warning("GraphRAG result leases deferred: %s", error)
                        break
                    last_renewal = time.monotonic()
                lease_lost = False
                with factory.store.batch():
                    for offset, (kind, job, result) in enumerate(
                        outcomes[index : index + RESULT_BATCH_SIZE]
                    ):
                        now = time.monotonic()
                        if offset and now - last_renewal >= WAVE_LEASE_SECONDS / 4:
                            remaining_ids = [
                                item["id"] for _, item, _ in outcomes[index + offset :]
                            ]
                            try:
                                factory.store.renew_leases(
                                    factory.owner, remaining_ids, WAVE_LEASE_SECONDS
                                )
                            except ValueError as error:
                                if str(error) not in {
                                    "stale graph job lease",
                                    "pilot store busy",
                                }:
                                    raise
                                LOGGER.warning(
                                    "GraphRAG result leases deferred: %s", error
                                )
                                lease_lost = True
                                break
                            last_renewal = time.monotonic()
                        try:
                            if kind == "error":
                                _inference_error(factory, job, result)
                            else:
                                factory._complete(job, result, time.time())
                        except (
                            ValueError,
                            TypeError,
                            AttributeError,
                            KeyError,
                        ) as error:
                            if isinstance(error, ValueError) and str(error) in {
                                "stale graph job lease",
                                "pilot store busy",
                            }:
                                LOGGER.warning("GraphRAG result deferred: %s", error)
                            elif kind == "completed":
                                try:
                                    _invalid_content(factory, job, result, error)
                                except ValueError as retry_error:
                                    if str(retry_error) != "stale graph job lease":
                                        raise
                                    LOGGER.warning(
                                        "GraphRAG result already checkpointed; projection will recover"
                                    )
                            else:
                                raise
                        except Exception as error:
                            unexpected = error
                if lease_lost:
                    break
            apply_seconds = time.monotonic() - applying
            LOGGER.info(
                "GraphRAG HTTP wave operations=%s http_peak=%s concurrency=%s seconds=%.3f "
                "prepare_seconds=%.3f apply_seconds=%.3f submits=%s polls=%s "
                "submit_seconds_sum=%.3f poll_seconds_sum=%.3f",
                len(futures),
                wave.peak,
                factory.concurrency,
                time.monotonic() - started,
                prepare_seconds,
                apply_seconds,
                wave.submits,
                wave.polls,
                wave.submit_seconds,
                wave.poll_seconds,
            )
            if unexpected is not None:
                raise unexpected
    return processed
