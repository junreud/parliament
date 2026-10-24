"""Packed GraphRAG jobs retain full history and SQL-visible routing."""

import json
import sqlite3

import pytest

from parliament_worker.graphrag.job_codec import decode_job, encode_job


def _job() -> dict:
    return {
        "id": "gr_example",
        "kind": "query_map",
        "key": "fixed-source-question",
        "state": "polling",
        "context": {
            "artifact_key": "map-1",
            "question_id": "question-1",
            "sources": ["source-1"],
            "exact_source_text": "공식 근거 구간 " * 800,
        },
        "request": {"messages": [{"role": "user", "content": "질문과 근거 " * 500}]},
        "result": None,
        "remote_id": "remote-1",
        "idempotency_key": "fixed-recovery-key",
    }


def test_packed_job_preserves_original_request_and_sql_routing() -> None:
    job = _job()
    encoded = encode_job(job)
    assert len(encoded) < len(json.dumps(job, ensure_ascii=False)) / 2
    assert decode_job(encoded) == job

    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE jobs(data TEXT NOT NULL)")
    db.execute("INSERT INTO jobs VALUES(?)", (encoded,))
    assert db.execute(
        "SELECT json_extract(data,'$.state'), "
        "json_extract(data,'$.context.artifact_key'), "
        "json_extract(data,'$.context.question_id') FROM jobs"
    ).fetchone() == ("polling", "map-1", "question-1")


def test_packed_job_rejects_corrupt_or_disagreeing_routing() -> None:
    value = json.loads(encode_job(_job()))
    value["state"] = "completed"
    with pytest.raises(ValueError, match="disagree"):
        decode_job(json.dumps(value))
    value["state"] = "polling"
    value["_packed"] = "invalid!"
    with pytest.raises(ValueError, match="invalid packed"):
        decode_job(json.dumps(value))


def test_job_codec_reads_legacy_plain_json_and_bounds_size() -> None:
    legacy = {"state": "completed", "request": {"messages": []}}
    assert decode_job(json.dumps(legacy)) == legacy
    oversized = _job()
    oversized["request"]["messages"][0]["content"] = "A" * 4_000_001
    with pytest.raises(ValueError, match="limit"):
        encode_job(oversized)
