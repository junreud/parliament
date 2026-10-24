"""Question retrieval uses one consistent source and artifact snapshot."""

from test_graphrag_engine import drain, make_factory

from parliament_worker.graphrag import index
from parliament_worker.graphrag.query import submit_question


def test_question_snapshot_contains_current_graph_and_report(tmp_path):
    factory, source = make_factory(tmp_path)
    drain(factory)

    snapshot = factory.store.query_snapshot()

    assert [item["scope"] for item in snapshot["sources"]] == [source["scope"]]
    assert len(snapshot["artifacts"]["graph"]) == 1
    assert len(snapshot["artifacts"]["community"]) == 1
    assert snapshot["model"]["payload"]["model_signature"] == factory.model_signature
    assert snapshot["coverage"]["active_sources"] == 1


def test_question_snapshot_rejects_reports_after_source_retirement(tmp_path):
    factory, source = make_factory(tmp_path)
    drain(factory)
    assert (
        len(
            index.select_snapshot_artifacts(factory.store.query_snapshot(), "community")
        )
        == 1
    )

    factory.store.retire_source(source["scope"])
    assert (
        index.select_snapshot_artifacts(factory.store.query_snapshot(), "community")
        == []
    )


def test_question_submission_captures_index_once(tmp_path, monkeypatch):
    factory, _ = make_factory(tmp_path)
    drain(factory)
    captured = []
    original = factory.store.query_snapshot

    def capture():
        captured.append(True)
        return original()

    monkeypatch.setattr(factory.store, "query_snapshot", capture)
    result = submit_question(
        factory.store, "김가 의원이 발의한 법안은?", "local", factory.model_signature
    )

    assert result["state"] == "queued"
    assert captured == [True]
