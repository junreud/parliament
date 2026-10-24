"""A successful query retry must replace a failed map attempt for reduction."""

import json

from test_graphrag_engine import SIGNATURE, RemoteFixture, drain, make_factory
from test_graphrag_inputs import fixture_batch

from parliament_worker.graphrag.inputs import sources_from_batch
from parliament_worker.graphrag.query import question_status, submit_question


class FirstAnswerInvalid(RemoteFixture):
    """Return one completed but invalid answer, then valid retry outputs."""

    def __init__(self) -> None:
        super().__init__()
        self.invalid_sent = False

    def poll(self, key: str) -> dict:
        """Keep the failed remote request immutable across repeated polls."""
        body = self.accepted[key]
        payload = json.loads(body["messages"][1]["content"])
        if payload["task"].startswith("answer") and not self.invalid_sent:
            self.invalid_sent = True
            return {
                "state": "completed",
                "_modelMetadata": self.model,
                "result": {
                    "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]
                },
            }
        return super().poll(key)


def test_global_reduction_uses_completed_retry_after_failed_map(tmp_path) -> None:
    """The original failed job must not strand an otherwise complete question."""
    factory, _ = make_factory(tmp_path)
    drain(factory)
    factory.client = FirstAnswerInvalid()
    factory.retry_output_failures = True
    question = submit_question(
        factory.store, "공식 기록의 주제는?", "global", SIGNATURE
    )

    drain(factory, cycles=30)

    map_jobs = factory.store.jobs(kind="query_map")
    assert factory.client.invalid_sent
    assert any(job["state"] == "failed" for job in map_jobs)
    assert any(job["state"] == "completed" for job in map_jobs)
    assert question_status(factory.store, question["id"])["state"] == "completed"


def test_obsolete_query_job_reports_obsolete_after_new_source(tmp_path) -> None:
    """A source addition invalidates old question work without an inference failure."""
    factory, _ = make_factory(tmp_path)
    drain(factory)
    store = factory.store
    question = submit_question(store, "김가 법안?", "local", SIGNATURE)
    artifact = store.get_artifact("question", question["id"])
    assert artifact is not None and artifact["payload"]["jobs"]
    job_id = artifact["payload"]["jobs"][0]

    added = fixture_batch()
    added["documents"][0]["recordKey"] = "new-source"
    added["entities"][0]["id"] = "p-new"
    store.put_sources(sources_from_batch(added))
    store.update_job(job_id, state="obsolete")

    status = question_status(store, question["id"])
    assert status is not None
    assert status["outdatedIndex"] is True
    assert status["state"] == "obsolete"
    assert status["error"] == "index_changed"
