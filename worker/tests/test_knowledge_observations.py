"""Observation time is independent of first collection and content versions."""

import json
from datetime import timedelta

from test_knowledge import manifest

from parliament_worker.cli import main
from parliament_worker.knowledge.pipeline import collect_manifest, prepare_batch
from parliament_worker.knowledge.store import PilotStore


def test_document_exposes_latest_observation_without_changing_first_time_or_batch(
    tmp_path, now
):
    store = PilotStore(tmp_path)
    raw = "<main><p>합성 원문</p></main>".encode()
    first_report = collect_manifest(manifest(), lambda _: raw, store, "job-a", now)
    first = prepare_batch(manifest(), store, "job-a")
    latest = now + timedelta(days=1)
    second_report = collect_manifest(manifest(), lambda _: raw, store, "job-b", latest)
    second = prepare_batch(manifest(), store, "job-b")
    assert first_report["observations"][0]["observedAt"] == now.isoformat()
    assert second_report["observations"][0]["observedAt"] == latest.isoformat()
    assert first["documents"][0]["collectedAt"] == second["documents"][0]["collectedAt"]
    assert first["documents"][0]["observedAt"] == now.isoformat()
    assert second["documents"][0]["observedAt"] == latest.isoformat()
    assert first["id"] == second["id"]
    replay = collect_manifest(
        manifest(), lambda _: raw, store, "job-b", latest + timedelta(days=1)
    )
    assert replay == second_report
    store.close()


def test_operator_resealing_excludes_observation_time_from_batch_id(tmp_path, now):
    store = PilotStore(tmp_path / "store")
    raw = "<main><p>합성 원문</p></main>".encode()
    paths = []
    for index in range(2):
        job = f"job-{index}"
        collect_manifest(
            manifest(), lambda _: raw, store, job, now + timedelta(days=index)
        )
        candidate = tmp_path / f"candidate-{index}.json"
        candidate.write_text(json.dumps(prepare_batch(manifest(), store, job)))
        sealed = tmp_path / f"sealed-{index}.json"
        assert (
            main(
                [
                    "pilot",
                    "validate",
                    "--batch",
                    str(candidate),
                    "--output",
                    str(sealed),
                ]
            )
            == 0
        )
        paths.append(sealed)
    first, second = [json.loads(path.read_text()) for path in paths]
    assert first["documents"][0]["observedAt"] != second["documents"][0]["observedAt"]
    assert first["id"] == second["id"]
    store.close()
