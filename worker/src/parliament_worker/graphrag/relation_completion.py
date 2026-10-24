"""Validate source-bound relation decisions before private graph projection."""

from typing import Any

from parliament_worker.graphrag.activity_repair import validate_activity_link
from parliament_worker.graphrag.ex_officio import validate_ex_officio_link
from parliament_worker.graphrag.lineage_repair import validate_lineage
from parliament_worker.graphrag.policy import apply_review_policy
from parliament_worker.graphrag.policy_repair import validate_policy_link
from parliament_worker.graphrag.store import GraphStore

VALIDATORS = {
    "activity_role": validate_activity_link,
    "bill_lineage": validate_lineage,
    "bill_policy": validate_policy_link,
}


def materialize_relation(
    store: GraphStore, output: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any] | None:
    """Resolve a fixed source and run the matching relation proof contract."""
    task = context.get("relation_task")
    if task == "ex_officio_chair":
        dependencies = context.get("sources")
        if not isinstance(dependencies, list) or len(dependencies) != 2:
            raise ValueError("ex officio source dependencies missing")
        by_scope = {item["scope"]: item for item in store.sources()}
        selected = [by_scope.get(item.get("scope")) for item in dependencies]
        if any(item is None for item in selected):
            raise ValueError("ex officio source proof missing source")
        return apply_review_policy(validate_ex_officio_link(output, context, selected))
    if task not in VALIDATORS:
        return None
    dependencies = context.get("sources")
    if not isinstance(dependencies, list) or len(dependencies) != 1:
        raise ValueError("relation source dependency missing")
    scope = dependencies[0].get("scope")
    source = next((item for item in store.sources() if item["scope"] == scope), None)
    if source is None:
        raise ValueError("relation source proof missing source")
    return apply_review_policy(VALIDATORS[task](output, context, source))
