"""Sequence private GraphRAG planning without changing persisted requests."""

import time
from typing import TYPE_CHECKING

from parliament_worker.graphrag.activity_repair import plan_activity_links
from parliament_worker.graphrag.claim_repair import plan_claim_repairs
from parliament_worker.graphrag.community_enrichment import plan_evidence_enrichments
from parliament_worker.graphrag.ex_officio import plan_ex_officio_links
from parliament_worker.graphrag.index import plan_communities, plan_extractions
from parliament_worker.graphrag.lineage_repair import plan_lineage_repairs
from parliament_worker.graphrag.office_audit import typed_office_pairs
from parliament_worker.graphrag.office_repair import plan_office_repairs
from parliament_worker.graphrag.output_retries import plan_output_retries
from parliament_worker.graphrag.policy_repair import plan_policy_links
from parliament_worker.graphrag.prompts import PROMPT_VERSION
from parliament_worker.graphrag.query import plan_question_reductions

if TYPE_CHECKING:
    from parliament_worker.graphrag.engine import Factory


def plan_factory(factory: "Factory") -> dict[str, int]:
    """Recover work and prioritize source extraction before derived reports.

    Args:
        factory: Running private factory and its persistent GraphStore.

    Returns:
        Counts of newly planned logical jobs by family.
    """
    active_model = {
        "model_signature": factory.model_signature,
        "prompt_version": PROMPT_VERSION,
    }
    configured = factory.store.get_artifact("control", "model")
    returning_model = bool(configured and configured["payload"] != active_model)
    if not configured or configured["payload"] != active_model:
        factory.store.put_artifact("control", "model", {}, active_model)
    if returning_model or not factory._projections_recovered:
        factory.recover_projections(reactivate_cached=returning_model)
        factory._projections_recovered = True

    status = factory.store.status()
    retried = (
        plan_output_retries(
            factory.store, factory.model_signature, factory.queue_capacity
        )
        if factory.retry_output_failures and status["unresolved_failures"]
        else 0
    )
    reductions = plan_question_reductions(factory.store)
    active_jobs = sum(
        status["jobs"][state]
        for state in ("planned", "deferred", "submitting", "polling")
    )
    if active_jobs + retried + reductions >= factory.queue_capacity:
        return {
            "output_retries": retried,
            "office_repairs": 0,
            "ex_officio_links": 0,
            "lineage_repairs": 0,
            "policy_links": 0,
            "activity_links": 0,
            "reductions": reductions,
            "claim_repairs": 0,
            "communities": 0,
            "extractions": 0,
        }

    repaired = 0
    now = time.monotonic()
    if now - factory._last_office_repair_scan >= 60:
        repair_options = (
            {"typed_pairs": typed_office_pairs(factory.office_inputs)}
            if factory.office_inputs
            else {}
        )
        repaired = plan_office_repairs(
            factory.store,
            factory.model_signature,
            factory.queue_capacity,
            **repair_options,
        )
        factory._last_office_repair_scan = now
    extracted = plan_extractions(
        factory.store, factory.model_signature, factory.queue_capacity
    )
    claim_repairs = plan_claim_repairs(
        factory.store, factory.model_signature, factory.queue_capacity
    )
    return {
        "output_retries": retried,
        "office_repairs": repaired,
        "ex_officio_links": plan_ex_officio_links(
            factory.store, factory.model_signature, factory.queue_capacity
        ),
        "lineage_repairs": plan_lineage_repairs(
            factory.store, factory.model_signature, factory.queue_capacity
        ),
        "policy_links": plan_policy_links(
            factory.store, factory.model_signature, factory.queue_capacity
        ),
        "activity_links": plan_activity_links(
            factory.store, factory.model_signature, factory.queue_capacity
        ),
        "reductions": reductions,
        "claim_repairs": claim_repairs,
        "communities": plan_communities(
            factory.store, factory.model_signature, factory.queue_capacity
        )
        + plan_evidence_enrichments(
            factory.store, factory.model_signature, factory.queue_capacity
        ),
        "extractions": extracted,
    }
