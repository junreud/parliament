"""Synthetic provenance pilots never assert real political events."""

import importlib
import json
from datetime import timedelta

import httpx
import pytest

from parliament_worker.http import SafeFetcher, validate_official_url
from parliament_worker.versions import map_bill


def module(name):
    """Fail clearly when the desired provenance component is absent."""
    path = "parliament_worker.knowledge." + name
    assert importlib.util.find_spec("parliament_worker.knowledge"), "pilot is missing"
    return importlib.import_module(path)


def manifest():
    """Return explicitly synthetic source and identity declarations."""
    return {
        "id": "synthetic-pilot",
        "issueId": "synthetic-issue",
        "entities": [
            {"id": "person-a", "kind": "person", "name": "합성인", "aliases": []},
            {"id": "person-b", "kind": "person", "name": "합성인", "aliases": []},
        ],
        "documents": [
            {
                "id": "document-a",
                "sourceKey": "synthetic-source",
                "recordKey": "a",
                "sourceUrl": "https://www.mogef.go.kr/a",
                "format": "html",
                "bodySelector": "main",
            }
        ],
    }


def test_unknown_bill_result_is_not_assumed_proposed(now):
    raw = {
        "BILL_ID": "SYNTHETIC",
        "BILL_NAME": "[합성] 법안",
        "PROPOSE_DT": "2024-01-01",
        "PROC_RESULT": "[합성] 알 수 없는 상태",
        "DETAIL_LINK": "https://likms.assembly.go.kr/bill/a",
    }
    event = map_bill(
        {"observed_at": now, "record_key": "a", "payload_hash": "a" * 64},
        raw,
        "a" * 64,
    )
    assert event["stage"] == "unknown"


@pytest.mark.parametrize(
    "url",
    [
        "https://opinion.lawmaking.go.kr/a",
        "https://ampos.nanet.go.kr/a",
        "https://www.mogef.go.kr/a",
    ],
)
def test_verified_pilot_hosts_are_accepted_exactly(url):
    assert validate_official_url(url) == url
    with pytest.raises(ValueError):
        validate_official_url(url.replace(".go.kr", ".go.kr.evil.test"))


def test_html_segments_keep_codepoint_mentions_pending_and_ambiguous():
    extraction = module("extract").extract_document(
        b"<html><nav>navigation</nav><main><p>"
        + "😀 합성인 발표 예정.".encode()
        + b"</p><p>"
        + "다음 문맥".encode()
        + b"</p></main></html>",
        manifest()["documents"][0],
        manifest()["entities"],
    )
    assert extraction["bodyStatus"] == "available"
    assert [item["text"] for item in extraction["segments"]] == [
        "😀 합성인 발표 예정.",
        "다음 문맥",
    ]
    mention = extraction["segments"][0]["mentions"][0]
    assert (mention["start"], mention["end"]) == (2, 5)
    assert mention["candidatePersonIds"] == ["person-a", "person-b"]
    assert mention["personId"] is None and mention["decision"] == "pending"


def test_html_image_alt_needs_operator_selection_and_keeps_provenance():
    extract = module("extract").extract_document
    raw = (
        "<html><nav><img alt='합성인 외부 연결'></nav>"
        "<main><div class='profile'>"
        "<img src='/portrait.jpg' alt='합성기관 상임위원 합성인 증명사진'>"
        "</div></main></html>"
    ).encode()
    spec = manifest()["documents"][0]
    assert extract(raw, spec, manifest()["entities"])["segments"] == []
    selected = extract(
        raw,
        spec | {"imageAltSelector": ".profile img[alt]"},
        manifest()["entities"],
    )
    assert [segment["text"] for segment in selected["segments"]] == [
        "합성기관 상임위원 합성인 증명사진"
    ]
    assert "image-alt" in selected["segments"][0]["locator"]
    assert selected["segments"][0]["mentions"][0]["decision"] == "pending"
    assert selected["extractionVersion"] != extract(raw, spec, [])["extractionVersion"]


def test_manifest_rejects_unbounded_image_alt_selector():
    pipeline = module("pipeline")
    spec = manifest()
    spec["documents"][0]["imageAltSelector"] = "x" * 201
    with pytest.raises(ValueError, match="image alt selector"):
        pipeline.validate_manifest(spec)


def test_json_fields_and_unsupported_attachments_are_explicit():
    extract = module("extract").extract_document
    spec = manifest()["documents"][0] | {"format": "json", "jsonFields": ["row.NAME"]}
    result = extract(
        json.dumps({"row": {"NAME": "합성인"}}).encode(), spec, manifest()["entities"]
    )
    assert result["segments"][0]["locator"] == "json:row.NAME"
    assert result["segments"][0]["text"] == "합성인"
    for kind in ("hwp", "hwpx"):
        result = extract(b"unsupported", spec | {"format": kind}, [])
        assert result["bodyStatus"] == "unsupported_" + kind
        assert result["segments"] == []


def test_pdf_limits_and_scan_status(monkeypatch):
    extract = module("extract")
    monkeypatch.setattr(
        extract,
        "pdf_pages",
        lambda *args, **kwargs: {
            "pageCount": 2,
            "extractedPages": [1, 2],
            "texts": ["", ""],
        },
    )
    spec = manifest()["documents"][0] | {"format": "pdf"}
    assert (
        extract.extract_document(b"%PDF synthetic", spec, [])["bodyStatus"]
        == "scan_requires_ocr"
    )
    with pytest.raises(ValueError, match="size"):
        extract.extract_document(b"x" * 10_000_001, spec, [])


def test_pdf_child_timeout_and_max_pages_are_fail_closed(monkeypatch):
    import subprocess

    extract = module("extract")
    seen = []

    def timed_out(*args, **kwargs):
        seen.append(kwargs["timeout"])
        raise subprocess.TimeoutExpired("synthetic", 60)

    monkeypatch.setattr(extract.subprocess, "run", timed_out)
    spec = manifest()["documents"][0] | {"format": "pdf"}
    result = extract.extract_document(b"%PDF synthetic", spec, [])
    assert result["bodyStatus"] == "extraction_timeout" and seen == [60]


def test_observation_a_b_a_is_retained_and_same_job_replay_deduplicated(tmp_path, now):
    store = module("store").PilotStore(tmp_path)
    spec = manifest()["documents"][0]
    first = store.observe(spec, b"A", "job-a", now)
    second = store.observe(spec, b"B", "job-b", now + timedelta(days=1))
    third = store.observe(spec, b"A", "job-c", now + timedelta(days=2))
    replay = store.observe(spec, b"A", "job-c", now + timedelta(days=3))
    assert first["version"] == third["version"]
    assert third == replay and first["observationId"] != third["observationId"]
    assert [item["changed"] for item in store.observations("document-a")] == [
        True,
        True,
        True,
    ]
    assert len(list((tmp_path / "raw").rglob("*.bin"))) == 2
    assert not first["rawStorageKey"].startswith("/")
    assert (tmp_path / first["rawStorageKey"]).stat().st_mode & 0o077 == 0
    with pytest.raises(ValueError, match="job"):
        store.observe(spec, b"different", "job-c", now)
    store.close()


def test_failed_observation_is_distinct_from_unchanged(tmp_path, now):
    store = module("store").PilotStore(tmp_path)
    spec = manifest()["documents"][0]
    store.observe(spec, b"A", "job-a", now)
    store.observe(spec, b"A", "job-b", now)
    store.failure(spec, "job-c", now, "TimeoutError")
    rows = store.observations("document-a")
    assert [row["status"] for row in rows] == ["success", "success", "failed"]
    assert rows[1]["changed"] is False and rows[2]["changed"] is None
    store.close()


def test_prepare_replay_preserves_old_extraction_and_never_autoapproves(tmp_path, now):
    pipeline = module("pipeline")
    raw = "<main><p>합성인 예정</p></main>".encode()
    store = module("store").PilotStore(tmp_path)
    report = pipeline.collect_manifest(manifest(), lambda _: raw, store, "job-a", now)
    batch = pipeline.prepare_batch(manifest(), store, "job-a")
    assert report["failures"] == 0 and batch["activities"] == []
    assert len(batch["documents"]) == len(batch["evidence"]) == 1
    assert batch == pipeline.prepare_batch(manifest(), store, "job-a")
    assert all(
        mention["decision"] == "pending"
        for segment in batch["documents"][0]["segments"]
        for mention in segment["mentions"]
    )
    assert batch["contexts"] == [] and batch["relations"] == []
    changed = pipeline.prepare_batch(
        manifest(), store, "job-a", extractor_version="synthetic-next"
    )
    assert changed["documents"][0]["version"] == batch["documents"][0]["version"]
    assert (
        changed["documents"][0]["extractionVersion"]
        != batch["documents"][0]["extractionVersion"]
    )
    assert len(list((tmp_path / "extractions").rglob("*.json"))) == 2
    store.close()


def test_manifest_does_not_follow_unreviewed_body_links(tmp_path, now):
    pipeline = module("pipeline")
    calls = []

    def fetch(url):
        calls.append(url)
        return b'<main><a href="https://evil.test/a">link</a></main>'

    store = module("store").PilotStore(tmp_path)
    pipeline.collect_manifest(manifest(), fetch, store, "job-a", now)
    assert calls == ["https://www.mogef.go.kr/a"]
    store.close()


def test_review_validation_rejects_bad_offsets_or_uncited_approval(tmp_path, now):
    pipeline = module("pipeline")
    review = module("review")
    store = module("store").PilotStore(tmp_path)
    pipeline.collect_manifest(
        manifest(), lambda _: "<main><p>합성인</p></main>".encode(), store, "job-a", now
    )
    batch = pipeline.prepare_batch(manifest(), store, "job-a")
    review.validate_batch(batch)
    batch["documents"][0]["segments"][0]["mentions"][0]["end"] = 99
    with pytest.raises(ValueError, match="offset"):
        review.validate_batch(batch)
    batch = pipeline.prepare_batch(manifest(), store, "job-a")
    batch["relations"] = [
        {
            "id": "r",
            "subjectId": "person-a",
            "objectId": "person-b",
            "type": "speaker",
            "evidenceIds": [],
            "decision": "approved",
            "reason": "operator",
        }
    ]
    with pytest.raises(ValueError, match="evidence"):
        review.validate_batch(batch)
    store.close()


def test_import_requires_optin_and_sends_only_fixed_authenticated_endpoint(
    tmp_path, now
):
    publisher = module("review").KnowledgePublisher
    with pytest.raises(ValueError, match="opt"):
        publisher("http://127.0.0.1:8080", "synthetic-key")
    seen = []
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: (
                seen.append(request) or httpx.Response(200, json={"status": "draft"})
            )
        )
    )
    instance = publisher(
        "http://127.0.0.1:8080", "synthetic-key", enabled=True, client=client
    )
    batch = {
        "id": "a",
        "issueId": "i",
        "entities": [],
        "documents": [],
        "evidence": [],
        "relations": [],
        "activities": [],
        "contexts": [],
    }
    assert instance.import_batch(batch) == {"status": "draft"}
    assert str(seen[0].url) == "http://127.0.0.1:8080/admin/tracking/knowledge/batches"
    assert seen[0].headers["X-Parliament-Ingestion-Key"] == "synthetic-key"
    instance.close()


def test_same_raw_poll_has_stable_first_time_and_transition_but_new_observation(
    tmp_path, now
):
    store = module("store").PilotStore(tmp_path)
    pipeline = module("pipeline")
    raw = "<main><p>합성인</p></main>".encode()
    batches = []
    for index, content in enumerate((raw, raw, raw + b"B", raw)):
        job = f"job-{index}"
        pipeline.collect_manifest(
            manifest(), lambda _: content, store, job, now + timedelta(days=index)
        )
        batches.append(pipeline.prepare_batch(manifest(), store, job))
    a, same, b, returned = [batch["documents"][0] for batch in batches]
    assert a["collectedAt"] == same["collectedAt"] == returned["collectedAt"]
    assert a["observationId"] != same["observationId"]
    assert a["transitionId"] == same["transitionId"]
    assert a["transitionId"] != returned["transitionId"] != b["transitionId"]
    assert batches[0]["id"] == batches[1]["id"]
    assert batches[3]["id"] != batches[0]["id"]
    store.close()


def test_pdf_real_page_limit_is_checked_before_extracting_text():
    import io

    from pypdf import PdfWriter

    output = io.BytesIO()
    writer = PdfWriter()
    for _ in range(31):
        writer.add_blank_page(width=100, height=100)
    writer.write(output)
    extract = module("extract")
    with pytest.raises(ValueError, match="page_limit"):
        extract.pdf_pages(output.getvalue())


def test_revised_body_selection_reuses_original_without_overwriting_old_segments(
    tmp_path, now
):
    pipeline = module("pipeline")
    store = module("store").PilotStore(tmp_path)
    original = manifest()
    pipeline.collect_manifest(
        original,
        lambda _: "<main><p>합성인</p><section><p>문맥</p></section></main>".encode(),
        store,
        "job-a",
        now,
    )
    first = pipeline.prepare_batch(original, store, "job-a")
    revised = manifest()
    revised["documents"][0]["bodySelector"] = "main section"
    second = pipeline.prepare_batch(revised, store, "job-a")
    assert first["documents"][0]["version"] == second["documents"][0]["version"]
    assert (
        first["documents"][0]["extractionVersion"]
        != second["documents"][0]["extractionVersion"]
    )
    assert second["documents"][0]["segments"][0]["text"] == "문맥"
    assert len(list((tmp_path / "extractions").rglob("*.json"))) == 2
    store.close()


def test_license_notice_remains_source_metadata_when_footer_is_not_body():
    result = module("extract").extract_document(
        "<main><p>합성 기록</p></main><footer>공공누리 제1유형</footer>".encode(),
        manifest()["documents"][0],
        [],
    )
    assert result["licenseStatus"] == "allowed"
    assert [item["text"] for item in result["segments"]] == ["합성 기록"]


def test_pilot_cli_requires_import_optin_before_backend(monkeypatch, tmp_path):
    from parliament_worker.cli import main

    with pytest.raises(SystemExit):
        main(["pilot", "import", "--batch", str(tmp_path / "missing.json")])


def test_pilot_cli_local_collect_prepare_preserves_private_raw(monkeypatch, tmp_path):
    from parliament_worker.cli import main

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest()))
    module("cli")

    class Fetcher:
        def __init__(self, **kwargs):
            assert kwargs["max_bytes"] == 10_000_000

        def __call__(self, url, **kwargs):
            return "<main><p>😀 합성인</p></main>".encode()

        def close(self):
            pass

    monkeypatch.setattr("parliament_worker.knowledge.cli.SafeFetcher", Fetcher)
    directory = tmp_path / "private"
    batch_path = tmp_path / "batch.json"
    assert (
        main(
            [
                "pilot",
                "collect",
                "--manifest",
                str(manifest_path),
                "--output",
                str(directory),
                "--job-id",
                "synthetic-job",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "pilot",
                "prepare",
                "--manifest",
                str(manifest_path),
                "--output",
                str(directory),
                "--job-id",
                "synthetic-job",
                "--batch",
                str(batch_path),
            ]
        )
        == 0
    )
    assert main(["pilot", "validate", "--batch", str(batch_path)]) == 0
    assert batch_path.stat().st_mode & 0o077 == 0


def test_review_export_writes_separate_operator_guide_without_approving(tmp_path):
    from parliament_worker.cli import main

    batch = {
        "id": "a",
        "issueId": "i",
        "entities": [],
        "documents": [],
        "evidence": [],
        "relations": [],
        "activities": [],
        "contexts": [],
    }
    source = tmp_path / "candidate.json"
    source.write_text(json.dumps(batch))
    target = tmp_path / "review.json"
    assert (
        main(
            ["pilot", "review-export", "--batch", str(source), "--output", str(target)]
        )
        == 0
    )
    guide = json.loads((tmp_path / "review.review-guide.json").read_text())
    assert guide["publicationApprovalPerformed"] is False
    assert guide["reviewedBatchPath"] == target.name
    assert set(guide["fieldsToReview"]) == {
        "mentions",
        "relations",
        "entities",
        "activities",
        "contexts",
        "licenses",
    }
    assert json.loads(target.read_text())["relations"] == []


def test_pdf_failed_attempt_and_success_get_distinct_immutable_extractions(
    monkeypatch, tmp_path
):
    extract = module("extract")
    spec = manifest()["documents"][0] | {"format": "pdf"}
    raw = b"%PDF synthetic original"

    def fail(*args, **kwargs):
        raise ValueError("missing_pdf_dependency")

    monkeypatch.setattr(extract, "pdf_pages", fail)
    failed = extract.extract_document(raw, spec, [])
    monkeypatch.setattr(
        extract,
        "pdf_pages",
        lambda *args, **kwargs: {
            "pageCount": 1,
            "extractedPages": [1],
            "texts": ["합성 원문"],
        },
    )
    success = extract.extract_document(raw, spec, [])
    assert failed["extractionVersion"] != success["extractionVersion"]
    store = module("store").PilotStore(tmp_path)
    store.save_extraction(spec["id"], failed)
    store.save_extraction(spec["id"], success)
    assert len(list((tmp_path / "extractions").rglob("*.json"))) == 2
    assert extract.extract_document(raw, spec, []) == success
    store.close()
