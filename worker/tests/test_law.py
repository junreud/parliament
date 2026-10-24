"""Synthetic law contracts; these fixtures do not describe real legislation."""

import json

import httpx
import pytest

from parliament_worker.cli import main
from parliament_worker.knowledge.review import validate_batch
from parliament_worker.knowledge.store import PilotStore
from parliament_worker.law import collect_laws, prepare_law_batch
from parliament_worker.law_client import LawClient, LawError


def listing(*, singleton=False):
    """Return an official-shaped synthetic search page that echoes its OC."""
    row = {
        "법령ID": "999001",
        "법령일련번호": "999101",
        "법령명한글": "[합성] 예시법",
        "공포일자": "20260901",
        "시행일자": "20270101",
        "공포번호": "99999",
        "소관부처명": "[합성] 예시기관",
        "법령상세링크": "/DRF/lawService.do?OC=synthetic-secret&MST=999101",
    }
    return {
        "LawSearch": {"totalCnt": "1", "page": "1", "law": row if singleton else [row]}
    }


def detail():
    """Return immutable metadata and nested article/supplement text."""
    return {
        "법령": {
            "기본정보": {
                "법령ID": "999001",
                "법령명_한글": "[합성] 예시법",
                "공포일자": "20260901",
                "시행일자": "20270101",
                "공포번호": "99999",
                "소관부처": {"content": "[합성] 예시기관"},
            },
            "조문": {
                "조문단위": [
                    {
                        "조문번호": "1",
                        "조문내용": "[합성] 제1조 (목적) 예시 규정입니다.",
                        "항": [
                            {
                                "항내용": "[합성] 첫 항입니다.",
                                "호": {"호내용": "[합성] 첫 호입니다."},
                            }
                        ],
                    }
                ]
            },
            "부칙": {
                "부칙단위": {"부칙내용": ["[합성] 시행일은 2027년 1월 1일입니다."]}
            },
        }
    }


def client_for(handler):
    """Use actual HTTP serialization with only the transport substituted."""
    return LawClient(
        "synthetic-secret", client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def test_collection_pins_version_and_never_saves_search_credentials(tmp_path, now):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.host == "www.law.go.kr"
        assert request.url.params["OC"] == "synthetic-secret"
        if request.url.path.endswith("lawSearch.do"):
            return httpx.Response(200, json=listing(singleton=True))
        assert request.url.params["MST"] == "999101"
        assert "ID" not in request.url.params
        return httpx.Response(200, json=detail())

    store = PilotStore(tmp_path)
    client = client_for(handler)
    report = collect_laws(
        client,
        "[합성] 예시법",
        store=store,
        job_id="job-one",
        collected_at=now,
        max_records=3,
        max_pages=1,
    )
    assert report["successes"] == 1 and report["failures"] == 0
    assert report["complete"] is True
    assert len(calls) == 2
    observation = report["observations"][0]
    assert observation["spec"]["lawId"] == "999001"
    assert observation["spec"]["mst"] == "999101"
    assert observation["spec"]["promulgatedDate"] == "2026-09-01"
    assert observation["spec"]["effectiveDate"] == "2027-01-01"
    assert b"synthetic-secret" not in store.read_raw(observation)
    assert "synthetic-secret" not in json.dumps(report)
    batch = prepare_law_batch(report, store, issue_id="synthetic-law")
    validate_batch(batch)
    document = batch["documents"][0]
    assert document["publishedAt"].startswith("2026-09-01")
    assert document["datePrecision"] == "date"
    assert document["bodyStatus"] == "available"
    texts = [segment["text"] for segment in document["segments"]]
    assert "20270101" in texts
    assert "[합성] 첫 호입니다." in texts
    assert document["licenseStatus"] == "unknown"
    assert batch["activities"] == [] and batch["relations"] == []
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert b"synthetic-secret" not in path.read_bytes()
    # An explicit replay uses its saved run and never consults the remote API.
    replay = collect_laws(
        client,
        "[합성] 예시법",
        store=store,
        job_id="job-one",
        collected_at=now,
        max_records=3,
        max_pages=1,
    )
    assert replay == report and len(calls) == 2
    newer = collect_laws(
        client,
        "[합성] 예시법",
        store=store,
        job_id="job-two",
        collected_at=now,
        max_records=3,
        max_pages=1,
    )
    assert newer["observations"][0]["changed"] is False
    assert len(list(tmp_path.glob("raw/**/*.bin"))) == 1
    store.close()
    client.close()


@pytest.mark.parametrize(
    "response",
    [
        {"result": "사용자 검증 실패", "msg": "synthetic-secret"},
        {"LawSearch": {"totalCnt": "1", "law": [{"법령ID": "../bad"}]}},
        {"LawSearch": {"totalCnt": "2", "page": "1", "law": []}},
    ],
)
def test_authentication_and_malformed_pages_are_errors_without_secret(response):
    client = client_for(lambda request: httpx.Response(200, json=response))
    with pytest.raises(LawError) as caught:
        client.search("예시", page=1, page_size=3)
    assert "synthetic-secret" not in str(caught.value)
    client.close()


def test_authentication_redirect_is_not_followed():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(302, headers={"Location": "https://example.org/collect"})

    client = client_for(handler)
    with pytest.raises(LawError):
        client.search("예시", page=1, page_size=3)
    assert len(seen) == 1
    client.close()


def test_response_size_is_bounded_before_parsing():
    client = LawClient(
        "synthetic-secret",
        max_bytes=100,
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=b"x" * 101)
            )
        ),
    )
    with pytest.raises(LawError):
        client.search("예시", page=1, page_size=3)
    client.close()


@pytest.mark.parametrize(
    "change",
    [
        {"법령ID": "999002"},
        {"공포일자": "20261399"},
        {"공포일자": "20260801"},
    ],
)
def test_invalid_or_mismatched_details_leave_failed_observation(tmp_path, now, change):
    body = detail()
    body["법령"]["기본정보"].update(change)
    client = client_for(
        lambda request: httpx.Response(
            200, json=listing() if request.url.path.endswith("lawSearch.do") else body
        )
    )
    store = PilotStore(tmp_path)
    report = collect_laws(
        client,
        "예시",
        store=store,
        job_id="failed",
        collected_at=now,
        max_records=3,
        max_pages=1,
    )
    assert report["failures"] == 1 and report["successes"] == 0
    assert report["observations"][0]["status"] == "failed"
    assert not list(tmp_path.glob("raw/**/*.bin"))
    store.close()
    client.close()


def test_http_request_logs_hide_the_oc(caplog):
    with caplog.at_level("INFO"):
        client = client_for(lambda request: httpx.Response(200, json=listing()))
        client.search("예시", page=1, page_size=3)
        client.close()
    assert "synthetic-secret" not in caplog.text


def test_later_search_failure_preserves_successes_in_an_incomplete_report(
    tmp_path, now
):
    search = listing()
    search["LawSearch"]["totalCnt"] = "2"

    def handler(request):
        if request.url.path.endswith("lawService.do"):
            return httpx.Response(200, json=detail())
        if request.url.params["page"] == "2":
            return httpx.Response(503)
        return httpx.Response(200, json=search)

    store = PilotStore(tmp_path)
    client = client_for(handler)
    report = collect_laws(
        client,
        "예시",
        store=store,
        job_id="page-failure",
        collected_at=now,
        max_records=3,
        max_pages=2,
    )
    assert report["successes"] == 1 and report["failures"] == 1
    assert not report["complete"]
    assert (tmp_path / "runs/page-failure.json").exists()
    store.close()
    client.close()


def test_cli_stages_only_a_saved_batch_and_keeps_import_opt_in(tmp_path, monkeypatch):
    client = client_for(
        lambda request: httpx.Response(
            200,
            json=listing() if request.url.path.endswith("lawSearch.do") else detail(),
        )
    )
    monkeypatch.setattr(LawClient, "from_env", lambda: client)
    from parliament_worker.knowledge.review import KnowledgePublisher

    monkeypatch.setattr(
        KnowledgePublisher,
        "from_env",
        lambda: pytest.fail("read-only collection must not import"),
    )
    result = main(
        [
            "law",
            "collect",
            "--query",
            "예시",
            "--issue-id",
            "synthetic-law",
            "--output",
            str(tmp_path),
            "--job-id",
            "cli-job",
        ]
    )
    assert result == 0
    batch = next((tmp_path / "knowledge-batches").glob("batch_*.json"))
    assert json.loads(batch.read_text())["documents"]


def test_cli_import_requires_original_storage_before_network(monkeypatch):
    monkeypatch.setattr(
        LawClient, "from_env", lambda: pytest.fail("must fail before contacting API")
    )
    with pytest.raises(SystemExit):
        main(
            [
                "law",
                "collect",
                "--query",
                "예시",
                "--issue-id",
                "synthetic-law",
                "--import",
            ]
        )


def test_a_small_law_batch_uses_the_backend_segment_budget(tmp_path, now):
    body = detail()
    body["법령"]["조문"]["조문단위"] = [
        {"조문내용": f"[합성] 제{i}조 내용입니다."} for i in range(1, 121)
    ]
    client = client_for(
        lambda request: httpx.Response(
            200, json=listing() if request.url.path.endswith("lawSearch.do") else body
        )
    )
    store = PilotStore(tmp_path)
    report = collect_laws(
        client,
        "예시",
        store=store,
        job_id="longer",
        collected_at=now,
        max_records=3,
        max_pages=1,
    )
    batch = prepare_law_batch(report, store, issue_id="synthetic-law")
    assert batch["documents"][0]["bodyStatus"] == "available"
    assert "[합성] 제120조 내용입니다." in [
        segment["text"] for segment in batch["documents"][0]["segments"]
    ]
    assert len(batch["evidence"]) <= 2000
    store.close()
    client.close()


def test_cli_new_observation_preserves_the_first_batch_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(
        LawClient,
        "from_env",
        lambda: client_for(
            lambda request: httpx.Response(
                200,
                json=(
                    listing() if request.url.path.endswith("lawSearch.do") else detail()
                ),
            )
        ),
    )
    arguments = [
        "law",
        "collect",
        "--query",
        "예시",
        "--issue-id",
        "synthetic-law",
        "--output",
        str(tmp_path),
    ]
    assert main(arguments + ["--job-id", "first-job"]) == 0
    first = next((tmp_path / "knowledge-batches").glob("batch_*.json"))
    original = first.read_bytes()
    assert main(arguments + ["--job-id", "second-job"]) == 0
    assert first.read_bytes() == original
    assert len(list(tmp_path.glob("raw/**/*.bin"))) == 1
    snapshots = list((tmp_path / "knowledge-batches/second-job").glob("batch_*.json"))
    assert len(snapshots) == 1
    assert (
        json.loads(snapshots[0].read_text())["documents"][0]["observationId"]
        != json.loads(original)["documents"][0]["observationId"]
    )


def test_bounds_report_truncation_and_missing_dates_remain_unknown(tmp_path, now):
    search = listing()
    search["LawSearch"]["totalCnt"] = "10"
    search["LawSearch"]["law"][0]["시행일자"] = "00000000"
    body = detail()
    body["법령"]["기본정보"]["시행일자"] = "00000000"
    client = client_for(
        lambda request: httpx.Response(
            200, json=search if request.url.path.endswith("lawSearch.do") else body
        )
    )
    store = PilotStore(tmp_path)
    report = collect_laws(
        client,
        "예시",
        store=store,
        job_id="partial",
        collected_at=now,
        max_records=1,
        max_pages=1,
    )
    assert report["complete"] is False and report["totalCount"] == 10
    assert report["observations"][0]["spec"]["effectiveDate"] is None
    store.close()
    client.close()


def test_detail_with_echoed_credential_is_never_stored(tmp_path, now):
    body = detail()
    body["법령"]["unexpected"] = "synthetic-secret"
    client = client_for(
        lambda request: httpx.Response(
            200, json=listing() if request.url.path.endswith("lawSearch.do") else body
        )
    )
    store = PilotStore(tmp_path)
    report = collect_laws(
        client,
        "예시",
        store=store,
        job_id="secret",
        collected_at=now,
        max_records=3,
        max_pages=1,
    )
    assert report["failures"] == 1
    assert not list(tmp_path.glob("raw/**/*.bin"))
    assert "synthetic-secret" not in json.dumps(report)
    store.close()
    client.close()
