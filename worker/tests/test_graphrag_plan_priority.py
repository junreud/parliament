"""Changed source records must enter inference before stale community backlog."""

from copy import deepcopy

from test_graphrag_engine import make_factory
from test_graphrag_inputs import fixture_batch

from parliament_worker.graphrag.index import current_artifacts
from parliament_worker.graphrag.inputs import sources_from_batch


def test_new_source_extraction_precedes_existing_community_backlog(tmp_path):
    """One available queue slot belongs to the new source, not an old leaf."""
    factory, _ = make_factory(tmp_path)
    factory.queue_capacity = 1
    assert factory.plan()["extractions"] == 1
    for _ in range(4):
        factory.tick(1)
        for job in factory.store.jobs():
            if job["state"] == "polling":
                factory.store.update_job(job["id"], next_poll=0)
        if current_artifacts(factory.store, "graph"):
            break
    assert len(current_artifacts(factory.store, "graph")) == 1
    assert current_artifacts(factory.store, "community") == []

    second = deepcopy(fixture_batch())
    second["documents"][0]["id"] = "doc-b"
    second["documents"][0]["recordKey"] = "3"
    second["evidence"][0]["documentId"] = "doc-b"
    factory.store.put_sources(sources_from_batch(second))
    planned = factory.plan()

    assert planned["extractions"] == 1
    assert planned["communities"] == 0
    assert [
        job["kind"]
        for job in factory.store.jobs()
        if job["state"] in {"planned", "submitting", "polling"}
    ] == ["extract"]
