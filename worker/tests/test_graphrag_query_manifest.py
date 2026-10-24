"""Large global questions pin sources without repeating the whole roster."""

import json

from test_graphrag_engine import SIGNATURE, drain, make_factory

from parliament_worker.graphrag.index import dependencies_current
from parliament_worker.graphrag.query import submit_question


def test_global_map_and_reduce_pin_compact_source_manifest(tmp_path) -> None:
    """A map or reduce job keeps a small complete-corpus revision guard."""
    factory, _ = make_factory(tmp_path)
    drain(factory)
    question = submit_question(
        factory.store, "공식 기록의 주제는?", "global", SIGNATURE
    )
    maps = factory.store.jobs(kind="query_map")
    assert len(maps) == 2
    context = maps[0]["context"]
    for job in maps:
        assert "sources" not in job["context"]
        assert len(job["context"]["source_manifest"]) == 64
        assert dependencies_current(
            job["context"],
            {source["scope"]: source for source in factory.store.sources()},
        )
    assert (
        "sources"
        in factory.store.get_artifact("question", question["id"])["dependency"]
    )

    drain(factory)

    reductions = factory.store.jobs(kind="query_reduce")
    assert len(reductions) == 1
    assert "sources" not in reductions[0]["context"]
    assert reductions[0]["context"]["source_manifest"] == context["source_manifest"]


def test_manifest_detects_added_removed_and_changed_sources(tmp_path) -> None:
    """A compact guard must still reject every source-set transition."""
    factory, _ = make_factory(tmp_path)
    drain(factory)
    submit_question(factory.store, "공식 기록의 주제는?", "global", SIGNATURE)
    context = factory.store.jobs(kind="query_map")[0]["context"]
    sources = {source["scope"]: source for source in factory.store.sources()}
    assert dependencies_current(context, sources)
    scope = next(iter(sources))
    modified = json.loads(json.dumps(sources))
    modified[scope]["generation"] += 1
    assert not dependencies_current(context, modified)
    assert not dependencies_current(context, {})
    modified = json.loads(json.dumps(sources))
    modified["new-source"] = {
        "scope": "new-source",
        "fingerprint": "new-fingerprint",
        "generation": 1,
    }
    assert not dependencies_current(context, modified)
