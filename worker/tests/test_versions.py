"""Synthetic Java outbox/raw-row integration without a database or network."""

import json
from datetime import timedelta

import pytest
from test_processing import document

from parliament_worker.models import SourceDocument
from parliament_worker.processing import process_documents
from parliament_worker.storage import LocalRawStore
from parliament_worker.versions import VersionArchive


def test_unknown_java_records_are_archived_not_invented_events(tmp_path, now):
    message = {
        "outboxId": 7,
        "sourceKey": "unknown-source",
        "recordKey": "9001",
        "payloadHash": "a" * 40,
    }

    def load(_):
        return {
            "source_key": "unknown-source",
            "record_key": "9001",
            "payload_hash": "a" * 40,
            "api_code": "unknown",
            "raw_payload": {"SYNTHETIC": "fixture"},
            "observed_at": now,
        }

    archive = VersionArchive(tmp_path, load)
    path = archive.process(message)
    result = json.loads(path.read_text())
    assert result["sourceVersion"] == "a" * 40
    assert result["status"] == "unsupported_record_type"
    assert result["event"] is None
    assert list((tmp_path / "raw").rglob("*.json"))
    assert archive.process(message) == path


def test_bill_payload_maps_structural_stage_with_original_source_version(
    tmp_path, now, monkeypatch
):
    message = {
        "outboxId": 8,
        "sourceKey": "bills",
        "recordKey": "BILL9001",
        "payloadHash": "b" * 40,
    }
    row = {
        "source_key": "bills",
        "record_key": "BILL9001",
        "payload_hash": "b" * 40,
        "api_code": "synthetic-bill",
        "observed_at": now,
        "raw_payload": {
            "BILL_ID": "BILL9001",
            "BILL_NAME": "[합성] 테스트 법안",
            "PROPOSE_DT": "2026-10-06",
            "PROC_RESULT": "대안반영폐기",
            "DETAIL_LINK": "https://likms.assembly.go.kr/bill/billDetail.do?billId=BILL9001",
        },
    }
    archive = VersionArchive(tmp_path, lambda _: row)
    path = archive.process(message)
    result = json.loads(path.read_text())
    event = result["event"]
    assert event["type"] == "bill" and event["stage"] == "alternative"
    assert event["billId"] == "BILL9001" and event["summary"] is None
    assert event["version"].startswith("v_") and event["version"] != "b" * 40
    assert event["evidence"][0]["sourceVersion"] == "b" * 40
    assert event["occurredAt"] is None
    monkeypatch.setattr(
        "parliament_worker.versions.MAPPER_VERSION", "synthetic-assembly-parser-next"
    )
    revised_path = archive.process(message)
    revised = json.loads(revised_path.read_text())
    assert revised_path != path and path.exists()
    assert revised["event"]["version"] != event["version"]
    assert revised["event"]["evidence"] == event["evidence"]
    assert revised["sourceVersion"] == result["sourceVersion"] == "b" * 40
    assert len(list((tmp_path / "raw").rglob("*.json"))) == 1


def test_version_lookup_mismatch_fails_without_archiving_wrong_record(tmp_path, now):
    message = {
        "outboxId": 8,
        "sourceKey": "bills",
        "recordKey": "BILL9001",
        "payloadHash": "b" * 40,
    }
    with pytest.raises(ValueError, match="identity"):
        VersionArchive(
            tmp_path,
            lambda _: {
                "source_key": "wrong",
                "record_key": "BILL9001",
                "payload_hash": "b" * 40,
            },
        ).process(message)
    assert list(tmp_path.iterdir()) == []


def test_old_version_replay_after_correction_keeps_exact_original_payload(
    tmp_path, now
):
    from dataclasses import replace

    store = LocalRawStore(tmp_path)
    a = document(now)
    first = process_documents([a], store=store).events[0]
    process_documents(
        [replace(a, raw=b"changed version", collected_at=now + timedelta(hours=1))],
        store=store,
    )
    replay = process_documents(
        [replace(a, collected_at=now + timedelta(hours=2))], store=store
    ).events[0]
    assert replay == first
    store.close()
