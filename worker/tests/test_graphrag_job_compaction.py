"""Lossless offline GraphRAG job packing leaves every source revision intact."""

import hashlib
import sqlite3
from pathlib import Path

import pytest

from parliament_worker.graphrag.job_compaction import copy_packed_jobs
from parliament_worker.graphrag.store import GraphStore
from parliament_worker.graphrag.store_schema import canonical_json


def test_job_compaction_preserves_replay_and_all_versioned_rows(tmp_path: Path) -> None:
    source = GraphStore(tmp_path / "original")
    source.put_source("official:1", "version-1", {"text": "공식 원문"})
    source.put_artifact("graph", "official:1", {"source": "version-1"}, {"nodes": []})
    source.enqueue_many(
        [
            {
                "kind": "query_map",
                "key": f"logical-{index}",
                "request": {
                    "messages": [{"role": "user", "content": "고정 근거 " * 1_000}]
                },
                "context": {
                    "artifact_key": f"answer-{index}",
                    "question_id": "question-1",
                },
            }
            for index in range(50)
        ]
    )
    with sqlite3.connect(source.database) as database:
        for job in source.jobs():
            database.execute(
                "UPDATE jobs SET data=? WHERE id=?",
                (canonical_json(job), job["id"]),
            )
    jobs_before = source.jobs()
    status_before = source.status()
    source_hash = hashlib.sha256(source.database.read_bytes()).hexdigest()
    target_dir = tmp_path / "packed"
    target_dir.mkdir(mode=0o700)
    target = target_dir / "graph.sqlite3"

    result = copy_packed_jobs(source.database, target)

    assert result["jobCount"] == 50
    assert result["packedBytes"] < result["sourceBytes"]
    assert target.stat().st_mode & 0o777 == 0o600
    assert hashlib.sha256(source.database.read_bytes()).hexdigest() == source_hash
    packed = GraphStore(target_dir)
    assert packed.jobs() == jobs_before
    assert packed.status() == status_before
    assert packed.sources() == source.sources()
    assert packed.artifacts("graph") == source.artifacts("graph")
    with sqlite3.connect(target) as db:
        assert (
            db.execute(
                "SELECT count(*) FROM jobs WHERE json_extract(data,'$.state')='planned'"
            ).fetchone()[0]
            == 50
        )
    with pytest.raises(ValueError, match="unsafe"):
        copy_packed_jobs(source.database, target)
