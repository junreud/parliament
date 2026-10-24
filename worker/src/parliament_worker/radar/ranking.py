"""Transparent discovery heuristics; these scores are not factual confidence."""

import hashlib
import re
from datetime import datetime, timedelta
from difflib import SequenceMatcher

from parliament_worker.radar.models import Article, iso

STOP = {
    "국회",
    "정부",
    "대통령",
    "민주당",
    "국민의힘",
    "국힘",
    "총리",
    "오늘",
    "내일",
    "대한",
    "위해",
    "관련",
    "발표",
    "의원",
    "국감",
    "기자",
    "단독",
    "속보",
    "종합",
}
VALUE = (
    "법안",
    "법원",
    "예산",
    "세금",
    "수사",
    "소방",
    "안전",
    "철도",
    "반도체",
    "연금",
    "주택",
    "개정",
    "기소",
    "지원",
    "감사",
    "해킹",
    "개인정보",
)


def normalized(title: str) -> str:
    """Ignore editorial wrappers and punctuation for copy detection."""
    return re.sub(
        r"[^가-힣a-zA-Z0-9]", "", re.sub(r"\[[^]]*\]|\([^)]*\)", "", title)
    ).lower()


def tokens(title: str) -> set[str]:
    """Use bounded Korean character bigrams without external model dependencies."""
    words = [
        word
        for word in re.findall(r"[가-힣a-zA-Z0-9]{2,}", title)
        if word not in STOP
        and not re.search(
            r"(?:법원장|대통령|총리|장관|위원장|대변인|지사|시장|의원|대표|차관|사무처장)(?:은|는|이|가|의)?$",
            word,
        )
    ]
    return {word[i : i + 2] for word in words for i in range(len(word) - 1)}


def similar(a: str, b: str) -> float:
    """Estimate headline similarity, never entity identity or factual agreement."""
    specific = [
        w
        for w in VALUE
        if w
        not in {
            "법안",
            "법원",
            "예산",
            "세금",
            "수사",
            "안전",
            "개정",
            "기소",
            "지원",
            "감사",
        }
    ]
    words_a = set(re.findall(r"[가-힣a-zA-Z]{3,}", a)) - STOP
    words_b = set(re.findall(r"[가-힣a-zA-Z]{3,}", b)) - STOP
    if words_a & words_b and any(w in a and w in b for w in specific):
        return 0.5
    x, y = tokens(a), tokens(b)
    return len(x & y) / max(1, min(len(x), len(y))) if len(x & y) >= 4 else 0.0


def candidates(
    items: list[Article],
    now: datetime,
    first_seen: dict[str, datetime],
    *,
    baseline: bool,
    trends: list[dict] | None = None,
    limit: int = 10,
) -> list[dict]:
    """Cluster headlines, discount copies and rank useful beginner questions.

    Args:
        items: Attributed recent metadata.
        now: Collection time.
        first_seen: Stable observation history, not publication claims.
        baseline: Whether 12 hours of real observations exist.
        trends: Optional distinct search-interest observations.
        limit: Maximum number of distinct issue candidates.

    Returns:
        Ranked unreviewed discovery briefs with explicit limitations.
    """
    groups: list[list[Article]] = []
    for article in sorted(
        {a.url: a for a in items}.values(), key=lambda a: a.published_at, reverse=True
    ):
        best = max(
            groups,
            key=lambda g: max(similar(article.title, a.title) for a in g[:5]),
            default=None,
        )
        if best and max(similar(article.title, a.title) for a in best[:5]) >= 0.42:
            best.append(article)
        else:
            groups.append([article])
    ranked = []
    for group in groups:
        representatives: list[Article] = []
        for article in group:
            if not any(
                SequenceMatcher(
                    None, normalized(article.title), normalized(a.title)
                ).ratio()
                >= 0.82
                for a in representatives
            ):
                representatives.append(article)
        lead = max(group, key=lambda a: (len(tokens(a.title)), a.published_at))
        recent = sum(
            now - timedelta(hours=6) < first_seen.get(a.id, a.published_at) <= now
            for a in group
        )
        previous = sum(
            now - timedelta(hours=12)
            < first_seen.get(a.id, a.published_at)
            <= now - timedelta(hours=6)
            for a in group
        )
        growth = (
            "no-baseline"
            if not baseline
            else (
                "new"
                if recent and not previous
                else "rising" if recent > previous else "steady"
            )
        )
        matches = [
            t
            for t in (trends or [])
            if len(t["keyword"]) >= 2
            and any(t["keyword"].replace(" ", "") in normalized(a.title) for a in group)
        ]
        publishers = sorted({a.publisher for a in group})
        value = [word for word in VALUE if any(word in a.title for a in group)]
        score = (
            min(30, len(representatives) * 5)
            + min(20, len(publishers) * 5)
            + min(20, len(value) * 5)
            + (10 if matches else 0)
            + (10 if (now - lead.published_at).total_seconds() < 86400 else 0)
            + (10 if growth == "rising" else 0)
        )
        identity = hashlib.sha256(min(a.url for a in group).encode()).hexdigest()[:16]
        ranked.append(
            {
                "id": "news_" + identity,
                "title": lead.title,
                "question": "무슨 일이 있었고, 어디까지 확인됐을까요?",
                "reason": f"{len(publishers)}개 매체의 보도 {len(group)}건을 묶었습니다. "
                + (
                    f"{', '.join(value[:3])}의 배경과 현재 단계를 설명할 가치가 있습니다."
                    if value
                    else "발언·사건의 전후 맥락과 원문을 확인할 후보입니다."
                ),
                "score": score,
                "articleCount": len(group),
                "publisherCount": len(publishers),
                "independentSignals": len(representatives),
                "growth": {"status": growth, "recent": recent, "previous": previous},
                "searchSignals": matches,
                "publishedAt": iso(max(a.published_at for a in group)),
                "articles": [
                    a.public()
                    for a in sorted(group, key=lambda a: a.published_at, reverse=True)[
                        :5
                    ]
                ],
                "evidence": [],
                "reviewStatus": "unreviewed",
            }
        )
    return sorted(ranked, key=lambda c: (c["score"], c["publishedAt"]), reverse=True)[
        :limit
    ]
