"""Validation failures retain a safe reason without exposing generated text."""

import json

from test_graphrag_engine import make_factory


def test_invalid_graph_quote_records_reason_code(tmp_path):
    """A real rejected model completion should identify its validation gate."""
    factory, _ = make_factory(tmp_path)
    original_poll = factory.client.poll

    def invalid_quote(key):
        response = original_poll(key)
        content = response["result"]["choices"][0]["message"]["content"]
        output = json.loads(content)
        output["relations"][0]["quote"] = "not in the official excerpt"
        response["result"]["choices"][0]["message"]["content"] = json.dumps(output)
        return response

    factory.client.poll = invalid_quote
    factory.plan()
    factory.tick(1)
    polling = next(job for job in factory.store.jobs() if job["state"] == "polling")
    factory.store.update_job(polling["id"], next_poll=0)
    factory.tick(1)

    failed = factory.store.get_job(polling["id"])
    assert failed["state"] == "failed"
    assert failed["error"] == "generated_content_validation_failed"
    assert failed["metadata"]["validation_reason"] == "graph_quote_absent_or_ambiguous"
    assert "official excerpt" not in json.dumps(failed["metadata"])


def test_truncated_completion_records_length_reason_and_retryable_error(tmp_path):
    """An output limit is a completion failure, not a rejected graph claim."""
    factory, _ = make_factory(tmp_path)
    original_poll = factory.client.poll

    def truncated_output(key):
        response = original_poll(key)
        choice = response["result"]["choices"][0]
        choice["finish_reason"] = "length"
        choice["message"]["content"] = '{"groups": [   '
        return response

    factory.client.poll = truncated_output
    factory.plan()
    factory.tick(1)
    polling = next(job for job in factory.store.jobs() if job["state"] == "polling")
    factory.store.update_job(polling["id"], next_poll=0)
    factory.tick(1)

    failed = factory.store.get_job(polling["id"])
    assert failed["state"] == "failed"
    assert failed["error"] == "inference_completion_invalid"
    assert failed["metadata"]["validation_reason"] == "completion_length_exhausted"
