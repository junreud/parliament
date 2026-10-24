"""Read current local-government source lists without asserting reviewed identity."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from bs4 import BeautifulSoup

if TYPE_CHECKING:
    from parliament_worker.roster.adapters import RosterPage


def _text(value: str, label: str) -> str:
    """Require bounded visible source text instead of filling an inferred fact."""
    value = value.strip()
    if not value or len(value) > 500:
        raise ValueError(f"missing or invalid local roster {label}")
    return value


def parse_namk(raw: bytes, *, current_term: str = "09") -> RosterPage:
    """Parse the selected current-term membership list and its reported total.

    Args:
        raw: Official membership HTML, preserved separately as immutable bytes.
        current_term: Explicit current source term; historical selections fail.

    Returns:
        Source-local person candidates and separately recorded vacant offices.
    """
    from parliament_worker.roster.adapters import RosterPage

    if not re.fullmatch(r"\d{2}", current_term):
        raise ValueError("invalid current term")
    soup = BeautifulSoup(raw, "html.parser")
    selected = soup.select('input[name="gsp_srch_class[]"][checked]')
    if len(selected) != 1 or selected[0].get("value") != current_term:
        raise ValueError("missing or mismatched current term")
    total_element = next(
        (
            element
            for element in soup.select("h2.sub-tit")
            if element.get_text(" ", strip=True).startswith("전국")
        ),
        None,
    )
    total_match = re.search(
        r"\(([\d,]+)\)", total_element.get_text() if total_element else ""
    )
    if total_match is None:
        raise ValueError("missing current member total")
    total = int(total_match.group(1).replace(",", ""))
    if not 1 <= total <= 1000:
        raise ValueError("invalid current member total")
    records: list[dict[str, Any]] = []
    exclusions: list[dict[str, str]] = []
    vacancies = 0
    for index, card in enumerate(soup.select(".mem-con-box")):
        region_element, holder_element = card.find("div"), card.find("p")
        anchor = card.find_parent("a")
        member_match = re.fullmatch(
            r"javascript:GSC_go_url\(\s*'gourl'\s*,\s*'view'\s*,\s*'mod'\s*,\s*'(\d+)'\s*\);?",
            str(anchor.get("href", "")) if anchor else "",
        )
        if member_match is None:
            raise ValueError("missing or invalid member identity")
        if region_element is None or holder_element is None:
            raise ValueError("missing current member card text")
        region = _text(region_element.get_text("", strip=True), "region")
        holder = _text(holder_element.get_text(" ", strip=True), "holder")
        district, name = holder.rsplit(" ", 1) if " " in holder else (holder, "")
        office_id = member_match.group(1)
        organization_name = _text(f"{region} {district}", "organization")
        if name in {"", "공석", "미정", "권한대행", "-"}:
            status = "vacant" if name == "공석" else "unknown_officeholder"
            vacancies += int(status == "vacant")
            exclusions.append(
                {
                    "organizationName": organization_name,
                    "organizationCode": office_id,
                    "status": status,
                    "evidenceLocator": f"HTML .mem-con-box[{index}] p",
                }
            )
            continue
        records.append(
            {
                "namespace": "NAMK_OFFICEHOLDER_SNAPSHOT",
                "sourceRecordId": f"{office_id}:{current_term}:{_text(name, 'name')}",
                "identityStatus": "source_local_candidate",
                "name": name,
                "organizationCode": office_id,
                "organizationNamespace": "NAMK_LOCAL_GOVERNMENT_MEMBER",
                "organizationName": organization_name,
                "position": "기초단체장 명부 표기",
                "termLabel": f"제{int(current_term)}기 명부",
                "currentness": "source_current_roster",
                "format": "html",
                "evidenceLocator": f"HTML .mem-con-box[{index}] div,p; member-record {office_id}",
                "excerpt": card.get_text(" ", strip=True),
            }
        )
    if not records and not exclusions:
        raise ValueError("missing current member cards")
    return RosterPage(records, total, vacancies, exclusions)


def parse_gaok(raw: bytes) -> RosterPage:
    """Parse organization-body member cards, excluding repeated board roles.

    Args:
        raw: Official association organizational-page HTML.

    Returns:
        The complete published card list, whose size is not an independent
        national statutory-universe count. Identity and tenure remain unreviewed.
    """
    from parliament_worker.roster.adapters import RosterPage

    soup = BeautifulSoup(raw, "html.parser")
    records: list[dict[str, Any]] = []
    for index, card in enumerate(soup.select(".other .box")):
        title_element, name_element = card.find("dt"), card.find("dd")
        if title_element is None or name_element is None:
            raise ValueError("missing current metropolitan member card")
        position = _text(title_element.get_text(" ", strip=True), "office")
        name = _text(name_element.get_text(" ", strip=True), "name")
        if position.endswith("도지사"):
            organization_name = position.removesuffix("지사")
        elif position.endswith("시장"):
            organization_name = position.removesuffix("장")
        else:
            raise ValueError("unrecognized metropolitan office")
        office_id = hashlib.sha256(position.encode()).hexdigest()
        records.append(
            {
                "namespace": "GAOK_OFFICEHOLDER_SNAPSHOT",
                "sourceRecordId": f"{office_id}:{name}",
                "identityStatus": "source_local_candidate",
                "name": name,
                "organizationCode": office_id,
                "organizationNamespace": "GAOK_LOCAL_GOVERNMENT_OFFICE",
                "organizationName": organization_name,
                "organizationIdentityStatus": "source_local_candidate",
                "position": position,
                "currentness": "source_current_roster",
                "format": "html",
                "evidenceLocator": f"HTML .other .box[{index}] dl dt,dd",
                "excerpt": card.get_text(" ", strip=True),
            }
        )
    if not 1 <= len(records) <= 50:
        raise ValueError("missing or invalid metropolitan member list")
    return RosterPage(records, len(records))


def _local_holder(
    *,
    name: str,
    position: str,
    site: str,
    organization_name: str,
    excerpt: str,
    locator: str,
    currentness: str = "source_current_roster",
) -> dict[str, Any]:
    """Keep a site-local snapshot identity pending cross-source identity review."""
    return {
        "namespace": "OFFICIAL_LOCAL_HEAD_SNAPSHOT",
        "sourceRecordId": f"{site}:{position}:{_text(name, 'name')}",
        "identityStatus": "source_local_candidate",
        "name": name,
        "organizationNamespace": "OFFICIAL_LOCAL_EXECUTIVE_SITE",
        "organizationCode": site,
        "organizationName": organization_name,
        "position": position,
        "currentness": currentness,
        "format": "html",
        "excerpt": excerpt,
        "evidenceLocator": locator,
    }


def parse_jejusi(raw: bytes) -> RosterPage:
    """Read the homepage's explicit mayor greeting without using an image/OCR."""
    from parliament_worker.roster.adapters import RosterPage

    soup = BeautifulSoup(raw, "html.parser")
    greetings = [
        element
        for element in soup.select("h4")
        if element.find("em")
        and element.find("em").get_text(strip=True) == "제주시장"
        and element.find("strong")
    ]
    if len(greetings) != 1:
        raise ValueError("missing or ambiguous current Jejusi mayor greeting")
    greeting = greetings[0]
    record = _local_holder(
        name=greeting.find("strong").get_text(strip=True),
        position="제주시장",
        site="jejusi.go.kr",
        organization_name="제주시",
        excerpt=greeting.get_text(" ", strip=True),
        locator="HTML h4 span em,strong",
    )
    return RosterPage([record], 1)


def parse_seogwipo(raw: bytes) -> RosterPage:
    """Read the mayor's current greeting paragraph, ignoring navigation names."""
    from parliament_worker.roster.adapters import RosterPage

    soup = BeautifulSoup(raw, "html.parser")
    greetings = soup.select("p.hello-greeting__name")
    if len(greetings) != 1:
        raise ValueError("missing or ambiguous current Seogwipo mayor greeting")
    excerpt = greetings[0].get_text(" ", strip=True)
    if not excerpt.startswith("서귀포시장 ") or not excerpt.endswith("입니다."):
        raise ValueError("invalid current Seogwipo mayor greeting")
    record = _local_holder(
        name=excerpt.removeprefix("서귀포시장 ").removesuffix("입니다."),
        position="서귀포시장",
        site="seogwipo.go.kr",
        organization_name="서귀포시",
        excerpt=excerpt,
        locator="HTML p.hello-greeting__name",
    )
    return RosterPage([record], 1)


def parse_goryeong_statement(raw: bytes) -> RosterPage:
    """Record a dated acting role without declaring current tenure from old news."""
    from parliament_worker.roster.adapters import RosterPage

    soup = BeautifulSoup(raw, "html.parser")
    body, date = soup.select_one("td.bV_contents"), soup.select_one("span.bV_date")
    if body is None or date is None:
        raise ValueError("missing dated Goryeong office statement")
    stamp = (
        datetime.strptime(date.get_text(strip=True), "%Y-%m-%d %H:%M")
        .replace(tzinfo=timezone(timedelta(hours=9)))
        .astimezone(timezone.utc)
        .isoformat()
    )
    text = body.get_text(" ", strip=True)
    matches = list(re.finditer(r"([가-힣]{2,8})\s+고령군수\s+권한대행", text))
    if len({match.group(1) for match in matches}) != 1:
        raise ValueError("missing or ambiguous dated acting officeholder")
    record = _local_holder(
        name=matches[0].group(1),
        position="고령군수 권한대행",
        site="goryeong.go.kr",
        organization_name="고령군",
        excerpt=matches[0].group(0),
        locator="HTML td.bV_contents; exact acting-role clause; span.bV_date",
        currentness="source_dated_office_statement",
    )
    record.update(
        sourcePublishedAt=stamp, qualificationObservedAt=stamp, datePrecision="second"
    )
    return RosterPage([record], 1)
