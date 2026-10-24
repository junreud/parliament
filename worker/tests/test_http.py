"""Network policy tests execute no real network requests."""

import httpx
import pytest

from parliament_worker.http import SafeFetcher, validate_official_url


def test_url_policy_blocks_credentials_http_lookalikes_and_ports():
    for url in (
        "http://www.korea.kr/a",
        "https://www.korea.kr.evil.test/a",
        "https://name:secret@www.korea.kr/a",
        "https://www.korea.kr:8443/a",
        "https://127.0.0.1/a",
    ):
        with pytest.raises(ValueError):
            validate_official_url(url)


def test_hwaseong_official_profile_host_is_exactly_allowed():
    url = "https://www.hscity.go.kr/mayor/introduce/profile.jsp"
    assert validate_official_url(url) == url
    for lookalike in (
        "https://www.hscity.go.kr.evil.test/mayor/introduce/profile.jsp",
        "https://name:secret@www.hscity.go.kr/mayor/introduce/profile.jsp",
        "http://www.hscity.go.kr/mayor/introduce/profile.jsp",
    ):
        with pytest.raises(ValueError):
            validate_official_url(lookalike)


def test_local_governance_committee_official_host_is_exactly_allowed():
    url = "https://www.balance.go.kr/base/board/read?boardNo=9778"
    assert validate_official_url(url) == url
    for lookalike in (
        "https://evil.www.balance.go.kr/base/board/read",
        "https://www.balance.go.kr.evil.test/base/board/read",
        "https://name:secret@www.balance.go.kr/base/board/read",
        "http://www.balance.go.kr/base/board/read",
    ):
        with pytest.raises(ValueError):
            validate_official_url(lookalike)


def test_redirect_destination_is_checked_before_next_request():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://evil.test/private"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetcher = SafeFetcher(client=client, resolver=lambda _: ["8.8.8.8"])
    with pytest.raises(ValueError):
        fetcher("https://www.korea.kr/a")
    assert len(calls) == 1


def test_private_dns_resolution_is_rejected():
    fetcher = SafeFetcher(resolver=lambda _: ["127.0.0.1"])
    with pytest.raises(ValueError, match="public"):
        fetcher("https://www.korea.kr/a")


def test_response_bytes_are_bounded():
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 101))
    )
    fetcher = SafeFetcher(client=client, resolver=lambda _: ["8.8.8.8"], max_bytes=100)
    with pytest.raises(ValueError, match="size"):
        fetcher("https://www.korea.kr/a")


def test_public_ajax_form_is_read_with_bounded_post():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, content=b'{"list":[]}')

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetcher = SafeFetcher(client=client, resolver=lambda _: ["8.8.8.8"])
    assert (
        fetcher(
            "https://www.president.go.kr/ajaxf/frBoard/bbsViewGalleryList.do",
            data={"pageNo": "1"},
        )
        == b'{"list":[]}'
    )
    assert requests[0].method == "POST"


def test_injected_redirect_following_client_cannot_bypass_official_host_policy():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://evil.test/private"})

    fetcher = SafeFetcher(
        client=httpx.Client(
            transport=httpx.MockTransport(handler), follow_redirects=True
        ),
        resolver=lambda _: ["8.8.8.8"],
    )
    with pytest.raises(ValueError):
        fetcher("https://www.korea.kr/a")
    assert len(calls) == 1
