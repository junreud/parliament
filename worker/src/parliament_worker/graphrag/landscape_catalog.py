"""Documented collection domains for the private data landscape."""

from typing import Any

PAGE_SIZE = 24

DOMAINS: list[dict[str, Any]] = [
    {
        "id": "assembly_people",
        "label": "국회의원 명부",
        "purpose": "공식 명부의 인물 식별자와 관측 시점 확인",
        "keys": ["roster_OPEN_ASSEMBLY_MONA_CD"],
        "next": "재임 기간과 발의·표결 연결의 근거 검수",
        "plan": "docs/data/current-politicians-sources.md",
    },
    {
        "id": "local_council",
        "label": "지방의원 명부",
        "purpose": "지방의회 소속과 출처별 인물 후보 확보",
        "keys": ["roster_NANET_CLIK_MEMBER"],
        "next": "인물 중복·현재 재임 여부 확인",
        "plan": "docs/data/current-politicians-sources.md",
    },
    {
        "id": "local_heads",
        "label": "지방자치단체장",
        "purpose": "광역·기초단체장 공식 명부 관측",
        "keys": [
            "roster_NAMK_OFFICEHOLDER_SNAPSHOT",
            "roster_GAOK_OFFICEHOLDER_SNAPSHOT",
            "roster_OFFICIAL_LOCAL_HEAD_SNAPSHOT",
        ],
        "next": "기관 단위 ID와 개인 신원 연결 검수",
        "plan": "docs/data/current-politicians-sources.md",
    },
    {
        "id": "central_people",
        "label": "중앙정부 인물·직위",
        "purpose": "기관 소개·임명 발표와 관측된 직위 분리",
        "keys": [
            "roster_KR_OFFICE_PROFILE_CANDIDATE",
            "official-president-status",
            "ministry-minister-profile",
            "humanrights-appointment-notice",
            "official-exofficio-rule",
        ],
        "next": "직위 효력일·대행·겸직 근거 검수",
        "plan": "docs/data/current-politicians-sources.md",
    },
    {
        "id": "parties",
        "label": "정당 명부",
        "purpose": "등록 정당과 대표 직위의 출처별 관측",
        "keys": ["roster_NEC_PARTY_HOLDER_SNAPSHOT"],
        "next": "등록일·현재 대표·대행 구분 검수",
        "plan": "docs/data/current-politicians-sources.md",
    },
    {
        "id": "bills",
        "label": "법안·첨부 원문",
        "purpose": "제22대 의안 상세와 대안 관계의 근거 확보",
        "keys": ["lawmaking-bill-detail", "lawmaking-bill-attachment"],
        "next": "전체 페이지·첨부 대조와 원천 식별자 검토",
        "plan": "docs/data/official-bill-graphrag-intake-2026-10-17.md",
    },
    {
        "id": "government",
        "label": "정부 발표·정책 안내",
        "purpose": "공식 발표, 일정, 정책 안내를 사건 단계별로 연결",
        "keys": ["ministry-press-release", "ministry-program-guide"],
        "next": "기관·주제 확대와 발표 이후의 실제 변화 확인",
        "plan": "docs/data/source-contracts.md",
    },
    {
        "id": "laws",
        "label": "법령",
        "purpose": "공포·시행일이 다른 법령 버전과 조문 근거 보관",
        "keys": ["law"],
        "next": "법안과 법령의 계보 및 전체 범위 확대",
        "plan": "docs/data/law-connector.md",
    },
    {
        "id": "votes",
        "label": "공개 표결",
        "purpose": "의안·의원·회차별 표결 사실 확인",
        "keys": ["nojepdqqaweusdfbi"],
        "next": "복합키 검증 후 실제 적재·그래프 연결",
        "plan": "docs/data/source-contracts.md",
    },
    {
        "id": "meetings",
        "label": "심사·회의",
        "purpose": "위원회 심사와 회의·의안 연결 확인",
        "keys": [
            "billjudgeconf",
            "billlwjudgeconf",
            "vconfbilllist",
            "vconfbillconflist",
        ],
        "next": "응답 계약 확인과 부모 의안별 재조회",
        "plan": "docs/data/source-contracts.md",
    },
]


def domain_for_key(source_key: str) -> str:
    """Classify a source key without suggesting completeness of its domain."""
    for domain in DOMAINS:
        if source_key in domain["keys"]:
            return str(domain["id"])
    return "other"
