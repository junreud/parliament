"""Flagged reports receive version-pinned private regeneration requests."""

from copy import deepcopy

from test_graphrag_engine import drain, make_factory
from test_graphrag_inputs import fixture_batch

from parliament_worker.graphrag.claim_repair import _flagged
from parliament_worker.graphrag.coverage import audit_coverage
from parliament_worker.graphrag.index import current_artifacts
from parliament_worker.graphrag.inputs import sources_from_batch
from parliament_worker.graphrag.output_retries import plan_output_retries


def test_factory_schedules_one_version_pinned_repair_without_changing_old_job(
    tmp_path,
) -> None:
    """A bad completed leaf starts a new request with its own immutable key."""
    factory, _ = make_factory(tmp_path)
    drain(factory)
    report = next(
        item
        for item in current_artifacts(factory.store, "community")
        if item["payload"]["level"] == 0 and item["payload"]["groups"][0]["claims"]
    )
    original_job = next(
        job
        for job in factory.store.jobs(kind="community")
        if job["state"] == "completed"
        and job["context"].get("artifact_key") == report["key"]
    )
    original_request = deepcopy(original_job["request"])
    bad_payload = deepcopy(report["payload"])
    bad_payload["groups"][0]["claims"][0]["text"] = "김가 의원이 E1을 대표발의함."
    bad_version = factory.store.put_artifact(
        "community", report["key"], report["dependency"], bad_payload
    )

    factory.plan()
    repairs = [
        job
        for job in factory.store.jobs(kind="community")
        if job["context"].get("quality_repair_for_version") == bad_version
    ]
    assert len(repairs) == 1
    assert repairs[0]["key"] != original_job["key"]
    assert repairs[0]["request"] != original_request
    assert original_job["request"] == original_request
    assert repairs[0]["context"]["artifact_key"] == report["key"]

    factory.plan()
    assert (
        sum(
            job["context"].get("quality_repair_for_version") == bad_version
            for job in factory.store.jobs(kind="community")
        )
        == 1
    )

    drain(factory)
    repaired = factory.store.get_artifact("community", report["key"])
    assert repaired["version"] != bad_version
    assert all(
        "E1" not in claim["text"]
        for group in repaired["payload"]["groups"]
        for claim in group["claims"]
    )
    assert bad_version in {
        item["version"]
        for item in factory.store.artifacts("community", current=False)
        if item["key"] == report["key"]
    }


def test_late_repair_cannot_replace_a_newer_report(tmp_path) -> None:
    """A changed current report wins over a response for an older version."""
    factory, _ = make_factory(tmp_path)
    drain(factory)
    report = next(
        item
        for item in current_artifacts(factory.store, "community")
        if item["payload"]["level"] == 0 and item["payload"]["groups"][0]["claims"]
    )
    bad_payload = deepcopy(report["payload"])
    bad_payload["groups"][0]["claims"][0]["text"] = "김가 의원이 E1을 대표발의함."
    bad_version = factory.store.put_artifact(
        "community", report["key"], report["dependency"], bad_payload
    )
    factory.plan()
    repair = next(
        job
        for job in factory.store.jobs(kind="community")
        if job["context"].get("quality_repair_for_version") == bad_version
    )
    factory.store.put_artifact(
        "community", report["key"], report["dependency"], report["payload"]
    )

    factory.project({**repair, "result": bad_payload})

    assert (
        factory.store.get_artifact("community", report["key"])["payload"]
        == report["payload"]
    )


def test_parent_report_repairs_after_clean_leaves(tmp_path) -> None:
    """A parent-only wording error must also receive a new model request."""
    factory, _ = make_factory(tmp_path)
    drain(factory)
    for number in (3, 4):
        batch = fixture_batch()
        batch["documents"][0]["recordKey"] = str(number)
        batch["entities"][0]["id"] = f"p-{number}"
        factory.store.put_sources([sources_from_batch(batch)[0]])
    drain(factory)
    parent = next(
        report
        for report in current_artifacts(factory.store, "community")
        if report["payload"]["level"] == 1
    )
    bad_payload = deepcopy(parent["payload"])
    bad_payload["groups"][0]["claims"][0]["text"] = "E1은 관련 법안을 발의함."
    bad_version = factory.store.put_artifact(
        "community", parent["key"], parent["dependency"], bad_payload
    )

    factory.plan()

    assert any(
        job["context"].get("quality_repair_for_version") == bad_version
        for job in factory.store.jobs(kind="community")
    )


def test_repair_waits_for_every_active_source_graph(tmp_path) -> None:
    """A newly observed source can change report routing before repair."""
    factory, _ = make_factory(tmp_path)
    drain(factory)
    report = next(
        item
        for item in current_artifacts(factory.store, "community")
        if item["payload"]["level"] == 0
    )
    bad_payload = deepcopy(report["payload"])
    bad_payload["groups"][0]["claims"][0]["text"] = "김가 의원이 E1을 대표발의함."
    bad_version = factory.store.put_artifact(
        "community", report["key"], report["dependency"], bad_payload
    )
    batch = fixture_batch()
    batch["documents"][0]["recordKey"] = "3"
    batch["entities"][0]["id"] = "p-3"
    factory.store.put_sources([sources_from_batch(batch)[0]])

    factory.plan()

    assert not any(
        job["context"].get("quality_repair_for_version") == bad_version
        for job in factory.store.jobs(kind="community")
    )


def test_failed_quality_repair_retries_while_flagged_version_is_current(
    tmp_path,
) -> None:
    """An existing bad report must not make its failed repair appear complete."""
    factory, _ = make_factory(tmp_path)
    drain(factory)
    report = next(
        item
        for item in current_artifacts(factory.store, "community")
        if item["payload"]["level"] == 0 and item["payload"]["groups"][0]["claims"]
    )
    bad_payload = deepcopy(report["payload"])
    bad_payload["groups"][0]["claims"][0]["text"] = "김가 의원이 E1을 대표발의함."
    bad_version = factory.store.put_artifact(
        "community", report["key"], report["dependency"], bad_payload
    )
    factory.plan()
    repair = next(
        job
        for job in factory.store.jobs(kind="community")
        if job["context"].get("quality_repair_for_version") == bad_version
    )
    factory.store.update_job(
        repair["id"], state="failed", error="generated_content_validation_failed"
    )

    assert plan_output_retries(factory.store, factory.model_signature, 256) == 1
    retry = next(
        job
        for job in factory.store.jobs(kind="community")
        if job["context"].get("retry_of") == repair["id"]
    )
    assert retry["key"] != repair["key"]
    assert retry["context"]["quality_repair_for_version"] == bad_version


def test_failed_quality_repair_does_not_retry_after_report_changes(tmp_path) -> None:
    """Retries cannot resurrect a repair for a superseded report version."""
    factory, _ = make_factory(tmp_path)
    drain(factory)
    report = next(
        item
        for item in current_artifacts(factory.store, "community")
        if item["payload"]["level"] == 0 and item["payload"]["groups"][0]["claims"]
    )
    bad_payload = deepcopy(report["payload"])
    bad_payload["groups"][0]["claims"][0]["text"] = "김가 의원이 E1을 대표발의함."
    bad_version = factory.store.put_artifact(
        "community", report["key"], report["dependency"], bad_payload
    )
    factory.plan()
    repair = next(
        job
        for job in factory.store.jobs(kind="community")
        if job["context"].get("quality_repair_for_version") == bad_version
    )
    factory.store.update_job(
        repair["id"], state="failed", error="generated_content_validation_failed"
    )
    factory.store.put_artifact(
        "community", report["key"], report["dependency"], report["payload"]
    )

    assert plan_output_retries(factory.store, factory.model_signature, 256) == 0


def test_selected_parent_claim_is_rebuilt_after_its_bad_leaf_is_repaired(
    tmp_path,
) -> None:
    """A copied child claim needs no separate parent repair request."""
    factory, _ = make_factory(tmp_path)
    drain(factory)
    for number in (3, 4):
        batch = fixture_batch()
        batch["documents"][0]["recordKey"] = str(number)
        batch["entities"][0]["id"] = f"p-{number}"
        factory.store.put_sources([sources_from_batch(batch)[0]])
    drain(factory)
    reports = {a["key"]: a for a in current_artifacts(factory.store, "community")}
    parent, leaf = next(
        (parent, reports[item["key"]])
        for parent in reports.values()
        if parent["payload"]["level"] == 1
        for item in parent["dependency"]["children"]
        if reports[item["key"]]["payload"]["groups"][0]["claims"]
    )
    bad_leaf_payload = deepcopy(leaf["payload"])
    bad_claim = bad_leaf_payload["groups"][0]["claims"][0]
    bad_claim["text"] = "김가 의원이 E1을 대표발의함."
    bad_leaf_version = factory.store.put_artifact(
        "community", leaf["key"], leaf["dependency"], bad_leaf_payload
    )
    bad_parent_payload = deepcopy(parent["payload"])
    bad_parent_payload["groups"][0]["claims"] = [deepcopy(bad_claim)]
    bad_parent_dependency = deepcopy(parent["dependency"])
    for item in bad_parent_dependency["children"]:
        if item["key"] == leaf["key"]:
            item["version"] = bad_leaf_version
    bad_parent_version = factory.store.put_artifact(
        "community", parent["key"], bad_parent_dependency, bad_parent_payload
    )

    factory.plan()
    repairs = [
        job
        for job in factory.store.jobs(kind="community")
        if job["context"].get("quality_repair_for_version")
        in {bad_leaf_version, bad_parent_version}
    ]
    assert [job["context"]["quality_repair_for_version"] for job in repairs] == [
        bad_leaf_version
    ]
    drain(factory)

    current_parents = [
        report
        for report in current_artifacts(factory.store, "community")
        if report["payload"]["level"] == 1
    ]
    assert all(report["version"] != bad_parent_version for report in current_parents)
    assert not any(_flagged(report) for report in current_parents)
    assert audit_coverage(factory.store.query_snapshot())["hierarchyReady"] is True
