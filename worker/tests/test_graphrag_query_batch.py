"""Completed map results are validated and committed as one durable wave."""

from test_graphrag_engine import SIGNATURE, drain, make_factory

from parliament_worker.graphrag.query import submit_question


def test_two_query_maps_finish_in_one_batch_without_losing_artifacts(
    tmp_path, monkeypatch
) -> None:
    """A real HTTP wave should checkpoint both map answers together."""
    from parliament_worker.graphrag import query_batch

    factory, _ = make_factory(tmp_path)
    drain(factory)
    factory.concurrency = 2
    submit_question(factory.store, "공식 기록의 주제는?", "global", SIGNATURE)
    assert len(factory.store.jobs(kind="query_map")) == 2
    sizes = []
    commit = query_batch.commit_query_maps

    def capture(factory, responses):
        sizes.append(len(responses))
        return commit(factory, responses)

    monkeypatch.setattr(query_batch, "commit_query_maps", capture)
    factory.tick(2)
    for job in factory.store.jobs(kind="query_map"):
        factory.store.update_job(job["id"], next_poll=0)
    factory.tick(2)

    maps = factory.store.jobs(kind="query_map")
    assert sorted(job["state"] for job in maps) == ["completed", "completed"]
    assert 2 in sizes
    assert all(
        factory.store.get_artifact("answer_map", job["context"]["artifact_key"])
        for job in maps
    )
