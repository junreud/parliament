"""Parse official current rosters; source identifiers never come from names alone."""

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from parliament_worker.roster.local_adapters import (
    parse_gaok,
    parse_goryeong_statement,
    parse_jejusi,
    parse_namk,
    parse_seogwipo,
)


@dataclass
class RosterPage:
    """One source page with its published universe and explicit vacancies."""

    records: list[dict[str, Any]]
    total: int
    vacancies: int = 0
    exclusions: list[dict[str, str]] = field(default_factory=list)


def _required(value: Any, label: str) -> str:
    """Require bounded source text instead of substituting an inferred identity."""
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise ValueError(f"missing or invalid roster {label}")
    return value.strip()


def _hash(value: str) -> str:
    """Use an explicit source-local record identity for sources without person IDs."""
    return hashlib.sha256(value.encode()).hexdigest()


def parse_assembly(raw: bytes) -> RosterPage:
    """Read the Assembly portal's current member directory, not all term alumni."""
    data = json.loads(raw)
    rows = data.get("resultList")
    total = data.get("resultCnt")
    if not isinstance(rows, list) or type(total) is not int or not 0 <= total <= 1000:
        raise ValueError("invalid assembly roster envelope")
    records = []
    for index, row in enumerate(rows):
        records.append(
            {
                "namespace": "OPEN_ASSEMBLY_MONA_CD",
                "format": "json",
                "sourceRecordId": _required(row.get("monaCd"), "member id"),
                "name": _required(row.get("hgNm"), "name"),
                "organizationCode": "assembly",
                "organizationNamespace": "KR_ASSEMBLY_ORGANIZATION",
                "organizationName": "대한민국 국회",
                "position": "국회의원",
                "party": row.get("polyNm"),
                "districtLabel": row.get("origNm"),
                "termLabel": row.get("unitNm"),
                "committeeLabel": row.get("cmitNm"),
                "currentness": "source_current_roster",
                "evidenceLocator": f"JSON $.resultList[{index}]",
            }
        )
    return RosterPage(records, total)


def parse_clik(raw: bytes) -> RosterPage:
    """Decode the literal JSON in the portal without evaluating JavaScript."""
    text = raw.decode("utf-8")
    match = re.search(r"var result\s*=\s*eval\((\[.*?\])\);", text, re.S)
    if not match:
        raise ValueError("missing local member result array")
    payload = json.loads(match.group(1))
    if not isinstance(payload, list) or len(payload) != 1:
        raise ValueError("invalid local member envelope")
    data = payload[0]
    total = int(data["total"].replace(",", "").strip())
    if not 0 <= total <= 20000 or not isinstance(data.get("list"), list):
        raise ValueError("invalid local member universe")
    records = []
    for index, item in enumerate(data["list"]):
        soup = BeautifulSoup(item["row"], "html.parser")
        check = soup.select_one('input[name="check_box[]"]')
        if check is None:
            raise ValueError("missing local member identity")
        fields = check["value"].split("┼")
        if len(fields) < 7:
            raise ValueError("invalid local member identity")
        labels = {}
        for row in soup.select("ul.rep > li"):
            label = row.find("span")
            if label:
                name = label.get_text(strip=True)
                label.extract()
                labels[name] = row.get_text(" ", strip=True)
        image = soup.find("img")
        organization = re.search(
            r"/assemblyinfo/\d{4}/(\d{6})/", image.get("src", "") if image else ""
        )
        org_name = _required(labels.get("지방의회명"), "council")
        # Some source rows lack a photo path; keep a provisional organization key.
        org_code = (
            organization.group(1) if organization else "unresolved_" + _hash(fields[5])
        )
        records.append(
            {
                "namespace": "NANET_CLIK_MEMBER",
                "format": "html",
                "sourceRecordId": _required(fields[5], "member id"),
                "name": _required(
                    labels.get("의원명", "").removesuffix(" 의원"), "name"
                ),
                "organizationCode": org_code,
                "organizationNamespace": "NANET_CLIK_COUNCIL",
                "organizationName": org_name,
                "organizationIdentityStatus": (
                    "source_code" if organization else "unresolved"
                ),
                "position": "지방의회의원",
                "party": labels.get("정당명"),
                "termLabel": labels.get("대수"),
                "districtLabel": labels.get("선거구"),
                "currentness": "source_current_roster",
                "evidenceLocator": f"embedded-result.list[{index}].row",
            }
        )
    return RosterPage(records, total)


def parse_parties(raw: bytes) -> RosterPage:
    """Preserve vacancies and acting leadership; exclude addresses and phones."""
    soup = BeautifulSoup(raw, "html.parser")
    table = next(
        (
            t
            for t in soup.find_all("table")
            if t.find("caption") and "정당등록현황" in t.find("caption").get_text()
        ),
        None,
    )
    if table is None:
        raise ValueError("missing registered party table")
    rows = table.select("tbody tr")
    records, exclusions, vacancies = [], [], 0
    for index, row in enumerate(rows):
        cells = row.find_all("td")
        if len(cells) < 3:
            raise ValueError("invalid registered party row")
        party, registered, holder = [
            cell.get_text(" ", strip=True) for cell in cells[:3]
        ]
        if "공석" in holder.replace(" ", ""):
            vacancies += 1
            exclusions.append({"organizationName": party, "status": "vacant"})
            continue
        role = "대표"
        if holder.startswith("권한대행"):
            role, holder = "대표 권한대행", holder.removeprefix("권한대행").strip()
        elif holder.startswith("비상대책위원장"):
            role, holder = (
                "비상대책위원장",
                holder.removeprefix("비상대책위원장").strip(),
            )
        organization = _hash(registered + ":" + party)
        for name in holder.split(","):
            name = _required(name, "party leader")
            records.append(
                {
                    "namespace": "NEC_PARTY_HOLDER_SNAPSHOT",
                    "format": "html",
                    "sourceRecordId": organization + ":" + name,
                    "identityStatus": "source_local_candidate",
                    "name": name,
                    "organizationCode": organization,
                    "organizationNamespace": "NEC_REGISTERED_PARTY_RECORD",
                    "organizationName": party,
                    "position": role,
                    "currentness": "source_current_roster",
                    "evidenceLocator": f"table registered-parties tbody tr[{index}] cells[0:3]",
                    "excerpt": " | ".join(
                        [party, registered, cells[2].get_text(" ", strip=True)]
                    ),
                }
            )
    return RosterPage(records, len(rows), vacancies, exclusions)


def page_url(source: dict[str, Any], page: int) -> str:
    """Generate the observed read-only screen request, including current filters."""
    adapter = source["adapter"]
    params = dict(source.get("params", {}))
    if adapter == "assembly":
        params.update(
            pageIndex=page,
            pageSize=source["pageSize"],
            pageUnit=source["pageSize"],
            cntsDivCd="NAAS",
            menuNo="600137",
        )
    elif adapter == "clik":
        params.update(
            collection="assemblyinfo",
            searchGubun="paging",
            searchSelect="Y",
            piSearch="PQ@@ASEMBY_YN@@Y",
            pageSize=source["pageSize"],
            pageIndex=page,
            page=page,
            isBasicSearchView="Y",
            detailSearchStatus="1",
            sort="ASEMBY_NM/ASC",
        )
    elif adapter == "namk":
        params.update(gsp_p=page)
    return (
        source["url"] + ("&" if "?" in source["url"] else "?") + urlencode(params)
        if params
        else source["url"]
    )


PARSERS = {
    "assembly": parse_assembly,
    "clik": parse_clik,
    "parties": parse_parties,
    "namk": parse_namk,
    "gaok": parse_gaok,
    "jejusi": parse_jejusi,
    "seogwipo": parse_seogwipo,
    "goryeong_statement": parse_goryeong_statement,
}
