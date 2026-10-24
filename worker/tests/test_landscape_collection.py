"""Collection counts stay separate from graph generation and verified publication."""

import json
from pathlib import Path

from parliament_worker.graphrag import landscape_collection as subject


def write(root: Path, name: str, value: dict) -> None:
    """Write a synthetic collector snapshot, never a real public record."""
    path = root / ".local/full-coverage" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def setup(root: Path, kind: str, progress: dict, *, state="running") -> None:
    """Select one synthetic collector in the explicit active-source registry."""
    write(
        root,
        "active-collections.json",
        {
            "schema": "parliament-active-collections-v1",
            "collectors": [
                {
                    "kind": kind,
                    "progress": "sample/progress.json",
                    "runtime": "sample/runtime.json",
                }
            ],
        },
    )
    write(
        root, "sample/progress.json", {"observedAt": "2026-10-22T00:00:00Z", **progress}
    )
    write(root, "sample/runtime.json", {"pid": 1234, "state": state})


def summary(root: Path, probe=lambda pid, script: "running") -> dict:
    return subject.collection_summary(root, process_probe=probe)


def test_missing_registry_is_unknown_not_zero(tmp_path):
    assert summary(tmp_path) is None


def test_law_body_count_does_not_imply_attachments_or_complete_collection(tmp_path):
    setup(
        tmp_path,
        "laws",
        {
            "expectedLaws": 10,
            "collectedLaws": 3,
            "attachmentReferences": 20,
            "archivedAttachmentReferences": 7,
            "errorCount": 0,
            "complete": True,
            "secret": "credential-sentinel",
        },
    )
    data = summary(tmp_path)
    card = data["pipelines"][0]
    assert card["metrics"][0]["completed"] == 3 and card["metrics"][0]["expected"] == 10
    assert card["metrics"][1]["completed"] == 7 and card["metrics"][1]["expected"] == 20
    assert not card["collectionVerified"] and not data["wholeCoverageComplete"]
    assert "credential-sentinel" not in json.dumps(data)
    assert "pid" not in card and "jobId" not in card


def test_law_closure_requires_final_metadata_and_original_hash_audit(tmp_path):
    progress = {
        "expectedLaws": 10,
        "collectedLaws": 10,
        "attachmentReferences": 20,
        "archivedAttachmentReferences": 20,
        "errorCount": 0,
        "complete": True,
        "catalogVerifiedUnchanged": True,
    }
    setup(tmp_path, "laws", progress)
    assert summary(tmp_path)["pipelines"][0]["collectionVerified"] is False
    setup(
        tmp_path,
        "laws",
        {
            **progress,
            "catalogMetadataVerifiedUnchanged": True,
            "originalHashesVerified": True,
        },
    )
    assert summary(tmp_path)["pipelines"][0]["collectionVerified"] is True


def test_empty_votes_are_closed_partitions_not_vote_rows(tmp_path):
    setup(
        tmp_path,
        "assembly-children",
        {
            "parentCount": 10,
            "bySource": {
                "nojepdqqaweusdfbi": {
                    "parentPartitionsExpected": 10,
                    "states": {"complete": 2, "empty": 3, "pending": 5},
                    "storedRows": 600,
                }
            },
        },
    )
    card = next(c for c in summary(tmp_path)["pipelines"] if c["id"] == "votes")
    assert card["metrics"][0]["completed"] == 5
    assert (
        card["metrics"][1]["completed"] == 600
        and card["metrics"][1]["expected"] is None
    )
    assert not card["collectionVerified"]


def test_unfinished_window_has_no_final_denominator_and_failure_stays_visible(tmp_path):
    setup(
        tmp_path,
        "government",
        {
            "sources": {
                "opm": {
                    "windowEnumerated": False,
                    "items": {"archived": 3, "failed": 1, "pending": 2},
                }
            },
            "files": {"archived": 4, "failed": 1},
            "originalWindowArchived": False,
            "catalogReconciliationComplete": False,
        },
    )
    card = summary(tmp_path)["pipelines"][0]
    assert (
        card["metrics"][0]["completed"] == 3 and card["metrics"][0]["expected"] is None
    )
    assert card["failureCount"] == 2 and not card["collectionVerified"]


def test_runtime_file_alone_is_not_proof_of_a_running_process(tmp_path):
    setup(
        tmp_path,
        "laws",
        {
            "expectedLaws": 10,
            "collectedLaws": 3,
            "attachmentReferences": 0,
            "archivedAttachmentReferences": 0,
            "errorCount": 0,
        },
    )
    card = summary(tmp_path, probe=lambda pid, script: "stopped")["pipelines"][0]
    assert card["activity"] == "stopped"


def test_counts_fail_closed_for_booleans_or_negative_values(tmp_path):
    setup(
        tmp_path,
        "laws",
        {
            "expectedLaws": 10,
            "collectedLaws": True,
            "attachmentReferences": 0,
            "archivedAttachmentReferences": 0,
            "errorCount": 0,
        },
    )
    assert summary(tmp_path)["pipelines"][0]["availability"] == "unavailable"


def test_registry_cannot_read_outside_private_collection_root(tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_text('{"secret":"credential-sentinel"}')
    write(
        tmp_path,
        "active-collections.json",
        {
            "schema": "parliament-active-collections-v1",
            "collectors": [
                {
                    "kind": "laws",
                    "progress": "../../outside.json",
                    "runtime": "sample/runtime.json",
                }
            ],
        },
    )
    data = summary(tmp_path)
    assert data["pipelines"][0]["availability"] == "unavailable"
    assert "credential-sentinel" not in json.dumps(data)


def test_unknown_meeting_total_and_source_defects_do_not_become_identity_approval(
    tmp_path,
):
    setup(
        tmp_path,
        "meeting-originals",
        {
            "allParentPartitionsComplete": False,
            "conferences": {"complete": 3, "pending": 2},
            "agendaRows": 30,
            "originalFiles": {"archived": 1, "pending": 4},
            "conferencesWithoutDownloadUrl": 0,
            "sourceDuplicateRows": 2,
            "invalidBillIdentityRows": 1,
            "complete": False,
        },
    )
    card = summary(tmp_path)["pipelines"][0]
    assert card["metrics"][0]["expected"] is None
    assert card["metrics"][1]["completed"] == 1
    assert card["sourceDefectRows"] == 3 and not card["collectionVerified"]
    assert not card["identityApproved"]


def test_progress_from_an_older_job_is_not_attached_to_a_new_runtime(tmp_path):
    setup(
        tmp_path,
        "laws",
        {
            "jobId": "old-job",
            "expectedLaws": 10,
            "collectedLaws": 3,
            "attachmentReferences": 0,
            "archivedAttachmentReferences": 0,
            "errorCount": 0,
        },
    )
    write(
        tmp_path,
        "sample/runtime.json",
        {"jobId": "new-job", "pid": 1234, "state": "running"},
    )
    assert summary(tmp_path)["pipelines"][0]["availability"] == "unavailable"


def test_malformed_registry_and_source_rows_fail_closed(tmp_path):
    write(
        tmp_path,
        "active-collections.json",
        {
            "schema": "parliament-active-collections-v1",
            "collectors": [{"kind": ["laws"], "progress": "x", "runtime": "x"}],
        },
    )
    assert summary(tmp_path)["pipelines"] == []
    setup(tmp_path, "government", {"sources": {"opm": []}, "files": {}})
    assert summary(tmp_path)["pipelines"][0]["availability"] == "unavailable"


def test_process_probe_checks_exact_collector_and_rejects_special_pids(monkeypatch):
    import subprocess

    monkeypatch.setattr(
        subject.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            [],
            0,
            stdout="worker/.venv/bin/python .local/full-coverage/20261022/collect_all_laws.py",
            stderr="",
        ),
    )
    assert subject._process(1234, "collect_all_laws.py") == "running"
    assert subject._process(1234, "collect_government.py") == "stopped"
    assert subject._process(0, "collect_all_laws.py") == "unknown"


def test_bill_originals_show_known_scope_without_claiming_all_bills(tmp_path):
    setup(
        tmp_path,
        "bill-attachments",
        {
            "knownSources": 10,
            "scannedSources": 8,
            "sourceStates": {"complete": 8, "failed": 2},
            "currentFiles": {"archived": 3, "pending": 17},
            "knownFileReferences": 20,
            "archivedFileReferences": 3,
            "knownScopeComplete": False,
            "nationalHtmlBillCoverageComplete": False,
        },
    )
    result = summary(tmp_path)
    assert len(result["pipelines"]) == 1
    card = result["pipelines"][0]
    assert card["domainIds"] == ["bills"]
    assert card["metrics"][0]["completed"] == 8
    assert card["metrics"][1]["expected"] is None
    assert not card["collectionVerified"] and not result["wholeCoverageComplete"]
    assert card["failureCount"] == 2


def test_bill_file_count_can_close_known_scope_while_national_scope_stays_open(
    tmp_path,
):
    setup(
        tmp_path,
        "bill-attachments",
        {
            "knownSources": 10,
            "scannedSources": 10,
            "sourceStates": {"complete": 10},
            "currentFiles": {"archived": 20},
            "knownFileReferences": 20,
            "archivedFileReferences": 20,
            "knownScopeComplete": True,
            "nationalHtmlBillCoverageComplete": False,
        },
    )
    result = summary(tmp_path)
    assert len(result["pipelines"]) == 1
    card = result["pipelines"][0]
    assert card["metrics"][1]["expected"] == 20
    assert not card["collectionVerified"]
