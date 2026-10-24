"""Official bill listing and detail boundaries for private graph intake."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from parliament_worker.bill_cli import _capacity_issue
from parliament_worker.bill_collect import collect_bill_cycle
from parliament_worker.bill_feed import (
    batch_from_bill_detail,
    parse_bill_detail,
    parse_bill_listing,
    parse_bill_listing_with_holds,
    parse_last_page,
)
from parliament_worker.cli import main
from parliament_worker.graphrag.inputs import read_sources, sources_from_batch
from parliament_worker.knowledge.review import validate_batch

LISTING = b"""
<table><tbody>
  <tr>
    <td class="subject"><a href="/gcom/nsmLmSts/out/2221909/detailRP">Example bill</a></td>
    <td data-th="\xec\xa0\x9c\xec\x95\x88\xec\x9e\x90(\xec\xa0\x9c\xec\x95\x88\xec\x9d\xbc\xec\x9e\x90)">Author</td>
    <td data-th="\xec\x9d\x98\xec\x95\x88\xeb\xb2\x88\xed\x98\xb8 (\xeb\x8c\x80\xec\x95\x88\xeb\xb2\x88\xed\x98\xb8)">2221909</td>
  </tr>
</tbody></table>
"""


def test_bill_capacity_halts_before_fetch_at_graph_size_limit(
    monkeypatch, tmp_path: Path
) -> None:
    graph_state = tmp_path / "graph"
    graph_input = tmp_path / "input"
    graph_state.mkdir()
    graph_input.mkdir()
    database = graph_state / "graph.sqlite3"
    with database.open("wb") as stream:
        stream.truncate(1_300_000_000)
    monkeypatch.setattr(
        "parliament_worker.bill_cli.shutil.disk_usage",
        lambda _: SimpleNamespace(free=20 * 1024**3),
    )

    assert _capacity_issue(graph_state, graph_input, tmp_path / "bill-state") == (
        "graph database reached the 1.3 GB bill intake limit"
    )


def test_bill_capacity_checks_destination_free_space(
    monkeypatch, tmp_path: Path
) -> None:
    graph_state = tmp_path / "graph"
    graph_input = tmp_path / "input"
    graph_state.mkdir()
    graph_input.mkdir()
    (graph_state / "graph.sqlite3").write_bytes(b"small")
    monkeypatch.setattr(
        "parliament_worker.bill_cli.shutil.disk_usage",
        lambda _: SimpleNamespace(free=9 * 1024**3),
    )

    assert _capacity_issue(graph_state, graph_input, tmp_path / "bill-state") == (
        "bill intake destination has less than 10 GiB free"
    )


def test_bill_cli_capacity_guard_prevents_network_or_state_creation(
    monkeypatch, tmp_path: Path
) -> None:
    graph_state = tmp_path / "graph"
    graph_input = tmp_path / "input"
    state = tmp_path / "bill-state"
    graph_state.mkdir()
    graph_input.mkdir()
    with (graph_state / "graph.sqlite3").open("wb") as stream:
        stream.truncate(1_300_000_000)
    monkeypatch.setattr(
        "parliament_worker.bill_cli.SafeFetcher",
        lambda: pytest.fail("capacity guard must run before the first HTTP request"),
    )

    assert (
        main(
            [
                "bills",
                "collect-graph",
                "--graph-state",
                str(graph_state),
                "--graph-input",
                str(graph_input),
                "--state",
                str(state),
            ]
        )
        == 1
    )
    assert not state.exists()


def test_listing_requires_matching_fixed_bill_number():
    rows = parse_bill_listing(LISTING)
    assert rows == [
        {
            "number": "2221909",
            "title": "Example bill",
            "url": "https://opinion.lawmaking.go.kr/gcom/nsmLmSts/out/2221909/detailRP",
        }
    ]
    with pytest.raises(ValueError, match="mismatch"):
        parse_bill_listing(LISTING.replace(b">2221909</td>", b">2221910</td>"))
    with pytest.raises(ValueError, match="mismatch"):
        parse_bill_listing(
            LISTING.replace(b">2221909</td>", b">2221910 (2221909)</td>")
        )


def test_listing_can_hold_one_mismatched_row_without_losing_valid_rows():
    malformed = LISTING.replace(b">2221909</td>", b">2221910</td>")
    raw = LISTING + malformed

    rows, holds = parse_bill_listing_with_holds(raw)

    assert [row["number"] for row in rows] == ["2221909"]
    assert holds == [{"row": 2, "printedNumber": "2221910", "linkNumber": "2221909"}]
    with pytest.raises(ValueError, match="multiple"):
        parse_bill_listing_with_holds(LISTING + malformed + malformed)


def test_last_page_is_read_from_official_pagination():
    html = (
        LISTING
        + b'<div class="pagination"><a class="icoCnt_last" href="?pageIndex=23&blockStartPage=21">last</a></div>'
    )
    assert parse_last_page(html) == 23


def test_detail_confirms_number_without_inferring_people():
    html = """
      <h2 class="subjectHead_tit">새 법률안</h2>
      <table><tbody>
        <tr><th scope="row">발의정보</th><td>아무개의원 등 3인, 제2221909호(2026. 10. 15.)</td></tr>
        <tr><th scope="row">제안이유 및 주요내용</th><td><pre>공식 제안 내용이다.</pre></td></tr>
      </tbody></table>
    """.encode()
    assert parse_bill_detail(html, "2221909") == {
        "title": "새 법률안",
        "proposal": "아무개의원 등 3인, 제2221909호(2026. 10. 15.)",
        "summary": "공식 제안 내용이다.",
    }
    with pytest.raises(ValueError, match="number"):
        parse_bill_detail(html, "2221910")


def test_bill_batch_is_private_versioned_and_has_no_person_role():
    detail = {
        "title": "새 법률안",
        "proposal": "아무개의원 등 3인, 제2221909호(2026. 10. 15.)",
        "summary": "제안 내용이다.",
    }
    batch = batch_from_bill_detail(
        "2221909", detail, b"official page", "2026-10-16T12:00:00+09:00"
    )
    validate_batch(batch)
    assert batch["relations"] == []
    assert batch["activities"] == []
    assert [entity["kind"] for entity in batch["entities"]] == ["bill"]
    assert batch["documents"][0]["licenseStatus"] == "unknown"
    source = sources_from_batch(batch)[0]
    assert source["scope"] == "lawmaking-bill-detail:2221909"
    assert source["payload"]["documentBillId"] == "bill-2221909"
    assert all("아무개" not in node["name"] for node in source["payload"]["entities"])


def test_bill_cycle_stages_once_and_keeps_a_sweep_cursor(tmp_path):
    graph_input = tmp_path / "input"
    state = tmp_path / "state"
    graph_input.mkdir()
    state.mkdir()
    pagination = b'<div class="pagination"><a class="icoCnt_last" href="?pageIndex=2&blockStartPage=1">last</a></div>'
    second = LISTING.replace(b"2221909", b"2221908")
    detail = """
      <h2 class="subjectHead_tit">새 법률안</h2>
      <table><tr><th scope="row">발의정보</th><td>아무개의원 등 3인, 제2221909호</td></tr>
      <tr><th scope="row">제안이유 및 주요내용</th><td><pre>제안 내용</pre></td></tr></table>
    """.encode()
    responses = {
        "https://opinion.lawmaking.go.kr/gcom/nsmLmSts/out/?pageIndex=1&blockStartPage=1": LISTING
        + pagination,
        "https://opinion.lawmaking.go.kr/gcom/nsmLmSts/out/?pageIndex=2&blockStartPage=1": second
        + pagination,
        "https://opinion.lawmaking.go.kr/gcom/nsmLmSts/out/2221909/detailRP": detail,
        "https://opinion.lawmaking.go.kr/gcom/nsmLmSts/out/2221908/detailRP": detail.replace(
            b"2221909", b"2221908"
        ),
    }

    def fetch(url: str) -> bytes:
        return responses[url]

    first = collect_bill_cycle(
        fetch,
        graph_input,
        state,
        [],
        observed_at="2026-10-16T12:00:00+09:00",
        hot_pages=1,
        sweep_pages=1,
        request_gap_seconds=0,
    )
    assert first["stagedBillCount"] == 2
    assert first["nextSweepPage"] == 2
    assert first["failures"] == []
    responses[
        "https://opinion.lawmaking.go.kr/gcom/nsmLmSts/out/2221909/detailRP"
    ] += b"<!-- volatile page decoration -->"
    second_run = collect_bill_cycle(
        fetch,
        graph_input,
        state,
        [],
        observed_at="2026-10-16T13:00:00+09:00",
        hot_pages=1,
        sweep_pages=1,
        request_gap_seconds=0,
    )
    assert second_run["stagedBillCount"] == 0
    assert second_run["unchangedBillCount"] == 2
    assert second_run["rawChangedSemanticSame"] == 1


def test_bill_cycle_does_not_advance_past_failed_detail(tmp_path):
    graph_input, state = tmp_path / "input", tmp_path / "state"
    graph_input.mkdir()
    state.mkdir()
    listing = (
        LISTING
        + b'<div class="pagination"><a class="icoCnt_last" href="?pageIndex=3">last</a></div>'
    )

    def fetch(url: str) -> bytes:
        if "pageIndex=1" in url:
            return listing
        if "pageIndex=2" in url:
            return listing.replace(b"2221909", b"2221908")
        raise KeyError("missing detail")

    report = collect_bill_cycle(
        fetch,
        graph_input,
        state,
        [],
        observed_at="2026-10-16T12:00:00+09:00",
        request_gap_seconds=0,
    )
    assert report["stagedBillCount"] == 0
    assert len(report["failures"]) == 2
    assert report["nextSweepPage"] == 2
    assert not (state / "cursor.json").exists()


def test_bill_cycle_holds_an_existing_curated_bill_source(tmp_path):
    graph_input, state = tmp_path / "input", tmp_path / "state"
    graph_input.mkdir()
    state.mkdir()
    listing = (
        LISTING
        + b'<div class="pagination"><a class="icoCnt_last" href="?pageIndex=1">last</a></div>'
    )
    detail_raw = """
      <h2 class="subjectHead_tit">새 법률안</h2>
      <table><tr><th scope="row">발의정보</th><td>제2221909호</td></tr></table>
    """.encode()
    prior = sources_from_batch(
        batch_from_bill_detail(
            "2221909",
            parse_bill_detail(detail_raw, "2221909"),
            detail_raw,
            "2026-10-16T12:00:00+09:00",
        )
    )[0]
    prior["payload"]["document"]["extractionVersion"] = "extract_editorial"

    def fetch(url: str) -> bytes:
        return detail_raw if url.endswith("detailRP") else listing

    report = collect_bill_cycle(
        fetch,
        graph_input,
        state,
        [prior],
        observed_at="2026-10-16T13:00:00+09:00",
        sweep_pages=0,
        request_gap_seconds=0,
    )
    assert report["stagedBillCount"] == 0
    assert report["curatedHold"] == ["2221909"]


def test_bill_cycle_reappearance_of_an_old_revision_is_a_new_observation(tmp_path):
    graph_input, state = tmp_path / "input", tmp_path / "state"
    graph_input.mkdir()
    state.mkdir()
    listing = (
        LISTING
        + b'<div class="pagination"><a class="icoCnt_last" href="?pageIndex=1">last</a></div>'
    )
    first_raw = """
      <h2 class="subjectHead_tit">새 법률안</h2>
      <table><tr><th scope="row">발의정보</th><td>제2221909호</td></tr>
      <tr><th scope="row">제안이유 및 주요내용</th><td><pre>초안 A</pre></td></tr></table>
    """.encode()
    current = {"detail": first_raw}

    def fetch(url: str) -> bytes:
        return current["detail"] if url.endswith("detailRP") else listing

    for stamp, raw in (
        ("2026-10-16T12:00:00+09:00", first_raw),
        (
            "2026-10-16T13:00:00+09:00",
            first_raw.replace("초안 A".encode(), "초안 B".encode()),
        ),
        ("2026-10-16T14:00:00+09:00", first_raw),
    ):
        current["detail"] = raw
        report = collect_bill_cycle(
            fetch,
            graph_input,
            state,
            [],
            observed_at=stamp,
            sweep_pages=0,
            request_gap_seconds=0,
        )
        assert report["stagedBillCount"] == 1
    assert len(list(graph_input.glob("bill_feed_batch_*.json"))) == 3
    current_source = read_sources([graph_input])[0]
    assert current_source["observedAt"] == "2026-10-16T05:00:00+00:00"
    assert "초안 A" in current_source["payload"]["units"][-1]["text"]


def test_bill_cycle_can_replay_one_page_without_losing_the_cursor(tmp_path):
    graph_input, state = tmp_path / "input", tmp_path / "state"
    graph_input.mkdir()
    state.mkdir()
    (state / "cursor.json").write_text('{"nextSweepPage":3}')
    listing = (
        LISTING
        + b'<div class="pagination"><a class="icoCnt_last" href="?pageIndex=4">last</a></div>'
    )
    detail_raw = """
      <h2 class="subjectHead_tit">새 법률안</h2>
      <table><tr><th scope="row">발의정보</th><td>제2221909호</td></tr></table>
    """.encode()

    def fetch(url: str) -> bytes:
        return detail_raw if url.endswith("detailRP") else listing

    report = collect_bill_cycle(
        fetch,
        graph_input,
        state,
        [],
        observed_at="2026-10-16T12:00:00+09:00",
        sweep_start=2,
        request_gap_seconds=0,
    )
    assert report["visitedPages"] == [1, 2]
    assert report["nextSweepPage"] == 3


def test_bill_cycle_out_of_order_sweep_keeps_unresolved_cursor(tmp_path):
    graph_input, state = tmp_path / "input", tmp_path / "state"
    graph_input.mkdir()
    state.mkdir()
    (state / "cursor.json").write_text('{"nextSweepPage":101}')
    listing = (
        LISTING
        + b'<div class="pagination"><a class="icoCnt_last" href="?pageIndex=120">last</a></div>'
    )
    detail_raw = """
      <h2 class="subjectHead_tit">새 법률안</h2>
      <table><tr><th scope="row">발의정보</th><td>제2221909호</td></tr></table>
    """.encode()

    def fetch(url: str) -> bytes:
        return detail_raw if url.endswith("detailRP") else listing

    report = collect_bill_cycle(
        fetch,
        graph_input,
        state,
        [],
        observed_at="2026-10-17T22:00:00+09:00",
        sweep_start=111,
        sweep_pages=10,
        request_gap_seconds=0,
    )
    assert report["visitedPages"] == [1, *range(111, 121)]
    assert report["stagedBillCount"] == 1
    assert report["nextSweepPage"] == 101
    assert (state / "cursor.json").read_text() == '{"nextSweepPage":101}'


def test_bill_cycle_stages_valid_rows_but_holds_mismatched_row(tmp_path):
    graph_input, state = tmp_path / "input", tmp_path / "state"
    graph_input.mkdir()
    state.mkdir()
    (state / "cursor.json").write_text('{"nextSweepPage":109}')
    pagination = b'<div class="pagination"><a class="icoCnt_last" href="?pageIndex=120">last</a></div>'
    valid = LISTING.replace(b"2221909", b"2221908")
    malformed = LISTING.replace(b"2221909", b"2221911").replace(
        b">2221911</td>", b">2221910</td>"
    )
    detail_raw = """
      <h2 class="subjectHead_tit">새 법률안</h2>
      <table><tr><th scope="row">발의정보</th><td>제2221908호</td></tr></table>
    """.encode()

    def fetch(url: str) -> bytes:
        if "pageIndex=109" in url:
            return valid + malformed + pagination
        if "pageIndex=1" in url:
            return LISTING + pagination
        if "2221908/detailRP" in url:
            return detail_raw
        if "2221909/detailRP" in url:
            return detail_raw.replace(b"2221908", b"2221909")
        raise KeyError(url)

    report = collect_bill_cycle(
        fetch,
        graph_input,
        state,
        [],
        observed_at="2026-10-17T22:00:00+09:00",
        sweep_start=109,
        sweep_pages=1,
        request_gap_seconds=0,
    )

    assert report["visitedPages"] == [1, 109]
    assert report["stagedBillCount"] == 2
    assert report["failures"] == [
        {
            "stage": "listing_row",
            "page": 109,
            "row": 2,
            "category": "bill_number_mismatch",
            "printedNumber": "2221910",
            "linkNumber": "2221911",
        }
    ]
    assert report["nextSweepPage"] == 109
    assert (state / "cursor.json").read_text() == '{"nextSweepPage":109}'
