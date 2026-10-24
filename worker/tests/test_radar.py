"""Safety and editorial behavior of the public news radar."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from parliament_worker.radar.feeds import SOURCES, NewsFetcher, parse_feed, parse_trends
from parliament_worker.radar.models import Article, canonical_url
from parliament_worker.radar.ranking import candidates
from parliament_worker.radar.store import RadarStore

NOW = datetime(2026, 10, 17, 8, tzinfo=timezone.utc)


def article(title: str, publisher: str, suffix: str, hours: int = 1) -> Article:
    return Article(
        title,
        f"https://www.yna.co.kr/view/{suffix}",
        publisher,
        NOW - timedelta(hours=hours),
    )


def test_feed_requires_real_date_and_preserves_attribution():
    raw = b"""<rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel>
    <item><title>&lt;b&gt;A&lt;/b&gt;</title><link>https://www.hani.co.kr/arti/politics/123.html?utm_source=rss</link><dc:date>2026-10-17T15:00:00+09:00</dc:date></item>
    <item><title>undated</title><link>https://www.hani.co.kr/a</link></item>
    <item><title>future</title><link>https://www.hani.co.kr/b</link><pubDate>Sun, 18 Oct 2026 08:00:00 GMT</pubDate></item>
    <item><title>local</title><link>https://localhost/a</link><pubDate>Sat, 17 Oct 2026 07:00:00 GMT</pubDate></item>
    </channel></rss>"""
    items = parse_feed(raw, SOURCES[2], NOW)
    assert len(items) == 1
    assert items[0].title == "A"
    assert items[0].publisher == "한겨레"
    assert items[0].url.endswith("123.html")
    assert items[0].published_at == datetime(2026, 10, 17, 6, tzinfo=timezone.utc)


def test_xml_entities_and_malformed_feeds_fail_closed():
    for raw in [b"<broken", b'<!DOCTYPE a [<!ENTITY x "boom">]><rss/>']:
        with pytest.raises(ValueError):
            parse_feed(raw, SOURCES[0], NOW)


def test_canonical_urls_keep_article_identity_remove_tracking_and_reject_credentials():
    assert (
        canonical_url("https://www.yna.co.kr/view/A?cid=1&utm_medium=x#top")
        == "https://www.yna.co.kr/view/A?cid=1"
    )
    with pytest.raises(ValueError):
        canonical_url("https://user:password@www.yna.co.kr/view/A")
    with pytest.raises(ValueError):
        canonical_url("http://www.yna.co.kr/view/A")


def test_syndicated_titles_do_not_inflate_independent_signals():
    items = [
        article("국회, 반도체 특별법 심사 착수", "연합뉴스", "1"),
        article("[속보] 국회, 반도체 특별법 심사 착수", "동아일보", "2"),
        article("반도체 특별법 심사 국회 쟁점은 노동시간", "한겨레", "3"),
    ]
    ranked = candidates(items, NOW, {}, baseline=False)
    assert len(ranked) == 1
    assert ranked[0]["articleCount"] == 3
    assert ranked[0]["publisherCount"] == 3
    assert ranked[0]["independentSignals"] == 2
    assert ranked[0]["growth"]["status"] == "no-baseline"
    assert ranked[0]["evidence"] == []
    assert ranked[0]["reviewStatus"] == "unreviewed"


def test_distinct_issues_not_merged_just_because_same_politician():
    items = [
        article("김민석 총리 소방관 순직 애도 안전대책 점검", "연합뉴스", "1"),
        article("김민석 총리 반도체 수출 대책 발표", "동아일보", "2"),
    ]
    assert len(candidates(items, NOW, {}, baseline=False)) == 2


def test_store_repeated_observation_does_not_create_growth(tmp_path: Path):
    store = RadarStore(tmp_path / "state.sqlite3")
    items = [article("국회 반도체 특별법 심사", "연합뉴스", "1")]
    store.observe(items, NOW)
    store.observe(items, NOW + timedelta(hours=1))
    assert len(store.articles(NOW + timedelta(hours=1))) == 1
    assert not store.has_baseline(NOW + timedelta(hours=1))
    assert store.has_baseline(NOW + timedelta(hours=13))
    store.close()


def test_trend_matches_are_search_signals_not_verified_facts():
    raw = b"""<rss xmlns:ht="https://trends.google.com/trending/rss"><channel><item>
    <title>rail</title><pubDate>Sat, 17 Oct 2026 07:00:00 GMT</pubDate>
    <ht:approx_traffic>2,000+</ht:approx_traffic></item></channel></rss>"""
    assert parse_trends(raw, NOW)[0]["keyword"] == "rail"
    assert parse_trends(raw, NOW)[0]["traffic"] == "2,000+"


def test_network_rejects_private_dns_redirects_and_oversize():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://127.0.0.1/private"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetch = NewsFetcher(client=client, resolver=lambda _: ["8.8.8.8"])
    with pytest.raises(ValueError):
        fetch(SOURCES[0].url)
    private = NewsFetcher(client=client, resolver=lambda _: ["127.0.0.1"])
    with pytest.raises(ValueError):
        private(SOURCES[0].url)
    large = NewsFetcher(
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, content=b"x" * 100)
            )
        ),
        resolver=lambda _: ["8.8.8.8"],
        max_bytes=10,
    )
    with pytest.raises(ValueError):
        large(SOURCES[0].url)


def test_same_subject_and_named_actor_form_one_issue_even_with_different_angles():
    items = [
        article("추미애 소방 재정 빨대 발언 논란 사과", "연합뉴스", "1"),
        article("추미애, 순직 소방관 빈소 찾아 지원 약속", "동아일보", "2"),
    ]
    assert len(candidates(items, NOW, {}, baseline=False)) == 1


def test_same_witness_in_one_audit_does_not_merge_unrelated_agendas():
    items = [
        article("서울고법원장 “제청권-임명권 간 우열 없어”", "동아일보", "1"),
        article(
            "서울고법원장 “법왜곡죄로 근거 없는 고소·고발…판사들 위축”", "동아일보", "2"
        ),
        article(
            "'李대통령 재판중단 불법인가'…서울고법원장 \"헌법조항 근거\"(종합2보)",
            "연합뉴스",
            "3",
        ),
        article(
            '이혼소송 중 주소 노출돼 살해…서울고법원장 "제도개선"', "연합뉴스", "4"
        ),
    ]
    assert len(candidates(items, NOW, {}, baseline=False)) == 4
