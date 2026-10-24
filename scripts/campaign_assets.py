"""Export original social artwork while preserving recorded review status."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any, List, Optional, Sequence

from PIL import Image, ImageDraw, ImageFont

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/marketing/beta-4w/assets"
SERIF = "/System/Library/Fonts/Supplemental/AppleMyungjo.ttf"
SANS = "/System/Library/Fonts/AppleSDGothicNeo.ttc"


def recorded_review(issue: dict[str, Any]) -> Optional[str]:
    """Accept a reviewed flag only with a valid, timezone-aware recorded date."""
    value = issue.get("reviewedAt")
    if issue.get("reviewStatus") != "reviewed" or not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if stamp.tzinfo else None


def render_card(
    stem: Path,
    title: Sequence[str],
    body: Sequence[str],
    note: Sequence[str],
    number: int,
    dark: bool,
    reviewed: bool = False,
) -> None:
    """Export a 1080×1350 SVG/PNG pair and reject overflowing copy.

    Args:
        stem: Destination without extension.
        title: At most three short heading lines.
        body: At most four explanatory lines.
        note: At most two source or contextual lines.
        number: Card order from one to five.
        dark: Whether to use the selected charcoal cover treatment.
        reviewed: Whether this exact copy has recorded human approval.
    """
    if len(title) > 3 or len(body) > 4 or len(note) > 2:
        raise ValueError("text exceeds the selected card layout")
    background = "#141719" if dark else "#F3F0E8"
    foreground = "#F3F0E8" if dark else "#30383A"
    secondary = "#B6B9B9" if dark else "#575F60"
    accent = "#B17279" if dark else "#7A4148"
    canvas = Image.new("RGB", (1080, 1350), background)
    draw = ImageDraw.Draw(canvas)
    pieces: List[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1350" viewBox="0 0 1080 1350">',
        "<title>"
        + escape(" ".join(title))
        + ("" if reviewed else " · 검토 전 초안")
        + "</title>",
        f'<rect width="1080" height="1350" fill="{background}"/>',
    ]

    def text(
        lines: Sequence[str],
        y: int,
        size: int,
        color: str,
        serif: bool = False,
        step: int = 64,
    ) -> None:
        font = ImageFont.truetype(SERIF if serif else SANS, size)
        family = "AppleMyungjo" if serif else "Apple SD Gothic Neo"
        for offset, line in enumerate(lines):
            baseline = y + offset * step
            if font.getlength(line) > 920:
                raise ValueError("text exceeds 920px: " + line)
            draw.text((80, baseline), line, font=font, fill=color, anchor="ls")
            pieces.append(
                f'<text x="80" y="{baseline}" fill="{color}" font-family="{family}" font-size="{size}">{escape(line)}</text>'
            )

    text(["나라의 근황"], 112, 43, foreground, True)
    text(
        [
            (
                "사건의 맥락 · 원문을 따라 읽기"
                if reviewed
                else "사건의 맥락 · 게시 검토 전 · 초안"
            )
        ],
        238,
        29,
        secondary,
    )
    for y in (156, 1205):
        draw.line((80, y, 1000, y), fill=secondary, width=1)
        pieces.append(f'<path d="M80 {y}L1000 {y}" stroke="{secondary}"/>')
    draw.rectangle((80, 290, 138, 295), fill=accent)
    pieces.append(f'<rect x="80" y="290" width="58" height="5" fill="{accent}"/>')
    text(title, 418, 80, foreground, True, 115)
    text(body, 818, 42, foreground, step=67)
    text(note, 1112, 28, secondary, step=43)
    text(["@flow_goverment"], 1260, 29, secondary)
    page_font = ImageFont.truetype(SANS, 29)
    draw.text(
        (1000, 1260), f"{number} / 5", font=page_font, fill=secondary, anchor="rs"
    )
    pieces.append(
        f'<text x="1000" y="1260" text-anchor="end" fill="{secondary}" font-family="Apple SD Gothic Neo" font-size="29">{number} / 5</text></svg>'
    )
    stem.parent.mkdir(parents=True, exist_ok=True)
    stem.with_suffix(".svg").write_text("".join(pieces), encoding="utf-8")
    canvas.save(stem.with_suffix(".png"))


def main() -> None:
    """Generate three carousels and their actual approval disclosure."""
    dossiers = json.loads((ROOT / "web/src/data/editorial-issues.json").read_text())[
        "issues"
    ]
    copy = [
        [
            (
                ["헌법에 넣자는 말,", "실제로 바뀌려면?"],
                ["뉴스 속 발언과 개헌 절차를", "나눠서 읽는 방법."],
                ["대한민국헌법 제128~130조"],
            ),
            (
                ["제안은", "시작입니다."],
                [
                    "국회 재적의원 과반수 또는",
                    "대통령의 발의로 개헌을 제안합니다.",
                    "개헌 의견을 밝힌 발언만으로",
                    "정식 제안까지 단정하지 않습니다.",
                ],
                ["근거: 대한민국헌법 제128조 제1항"],
            ),
            (
                ["공고 다음에는", "국회 의결이 있습니다."],
                [
                    "제안된 안은 20일 이상 공고합니다.",
                    "국회는 공고일부터 60일 이내 의결.",
                    "재적의원 3분의 2 이상의",
                    "찬성이 필요합니다.",
                ],
                ["근거: 대한민국헌법 제129조·제130조 제1항"],
            ),
            (
                ["국민투표도", "거쳐야 합니다."],
                [
                    "국회 의결 후 30일 이내 국민투표.",
                    "선거권자 과반수가 투표하고,",
                    "투표자 과반수가 찬성해야 합니다.",
                    "요건을 충족하면 확정·공포합니다.",
                ],
                ["근거: 대한민국헌법 제130조 제2~3항"],
            ),
            (
                ["그 뉴스는", "지금 어느 단계일까."],
                [
                    "말과 제안, 의결과 확정을 구분하기.",
                    "원문과 날짜를 함께 확인하기.",
                    "공개 웹에서는 배경과 다음 확인",
                    "지점까지 이어 읽도록 준비합니다.",
                ],
                ["검토 전 · 앱 공개 주소 연결 대기", "@flow_goverment · 의정의 흐름"],
            ),
        ],
        [
            (
                ["야스쿠니 논평,", "어디까지 확인됐을까."],
                ["정부가 유감을 표했다는 뉴스.", "발표와 행동의 근거를 나눠 봅니다."],
                ["외교부 논평 [26-832] · 2026.10.17"],
            ),
            (
                ["확인된 것은", "논평이 나왔다는 사실."],
                [
                    "외교부는 10월 17일",
                    "공물 봉납 및 참배에 관한",
                    "대변인 논평을 공개했습니다.",
                ],
                ["작성일과 개별 행동의 날짜는 구분합니다."],
            ),
            (
                ["평가는", "누구의 입장일까."],
                [
                    "논평은 한국 정부의",
                    "실망·유감과 반성 촉구를 담았습니다.",
                    "기관이 밝힌 평가에는",
                    "그 주체를 함께 적습니다.",
                ],
                ["근거: 외교부 논평 본문 두 문단"],
            ),
            (
                ["이 문서만으로", "단정하지 않을 것."],
                [
                    "특정인의 직접 참배 여부.",
                    "봉납과 직접 참배가 같은 행동인지.",
                    "추가 외교조치가 있었는지.",
                    "각각 별도 공식 자료가 필요합니다.",
                ],
                ["발표의 범위와 확인하지 못한 부분을 구분합니다."],
            ),
            (
                ["제목 다음에는", "발표의 범위를 읽기."],
                [
                    "누가 무엇을 발표했는지.",
                    "무엇은 아직 확인되지 않았는지.",
                    "의정의 흐름에서 원문과",
                    "다음 확인 지점을 연결합니다.",
                ],
                [
                    "검토 전 · 앱 공개 주소 연결 대기",
                    "출처: 외교부 · 사진·첨부파일 재사용 없음",
                ],
            ),
        ],
        [
            (
                ["대법관,", "누가 임명할까."],
                ["제청권·동의권·임명권.", "기사 속 역할을 나눠 읽습니다."],
                ["대한민국헌법 제104조 제1~3항"],
            ),
            (
                ["대법관의 절차는", "세 역할로 이어집니다."],
                ["대법원장이 제청하고,", "국회가 동의하고,", "대통령이 임명합니다."],
                ["근거: 대한민국헌법 제104조 제2항"],
            ),
            (
                ["대법원장은", "절차가 다릅니다."],
                [
                    "국회의 동의를 얻어",
                    "대통령이 임명합니다.",
                    "대법원장과 대법관을",
                    "같은 직책으로 읽지 않습니다.",
                ],
                ["근거: 대한민국헌법 제104조 제1항"],
            ),
            (
                ["그 밖의 법관도", "구분해야 합니다."],
                [
                    "대법원장·대법관이 아닌 법관은",
                    "대법관회의의 동의를 얻어",
                    "대법원장이 임명합니다.",
                ],
                ["근거: 대한민국헌법 제104조 제3항"],
            ),
            (
                ["역할을 알았다면,", "현재 단계를 확인하기."],
                [
                    "누구의 인사에 관한 뉴스인지.",
                    "제청·동의·임명 중 어디까지인지.",
                    "실제 안건과 발표 날짜를",
                    "따로 확인합니다.",
                ],
                [
                    "검토 전 · 특정 인사 진행 여부를 판정한 글 아님",
                    "@flow_goverment · 의정의 흐름",
                ],
            ),
        ],
    ]
    manifest = []
    approved_count = sum(recorded_review(issue) is not None for issue in dossiers)
    gallery = [
        "<!doctype html><html lang='ko'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>첫 콘텐츠 3편 · 게시 전 검토실</title><style>body{background:#f3f0e8;color:#30383a;font:17px/1.7 system-ui;margin:0;padding:32px}h1,h2{font-family:AppleMyungjo,serif}main{max-width:1400px;margin:auto}.cards{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px}img{width:100%;height:auto}section{margin:45px 0}.notice{padding:20px;border:1px solid #7a4148}a{color:#7a4148}@media(max-width:700px){.cards{grid-template-columns:1fr}body{padding:20px}}</style><main><h1>첫 콘텐츠 3편</h1>"
        + f"<p class='notice'>총 15장 · 운영자 원고 승인 {approved_count}/3편. 공개 주소 연결과 게시 당일 최신성 확인은 별도 조건입니다. 미승인 원고는 초안으로 표시합니다.</p>"
    ]
    for index, (issue, cards) in enumerate(zip(dossiers, copy), 1):
        asset = f"B{index:02}"
        reviewed_at = recorded_review(issue)
        reviewed = reviewed_at is not None
        disclosure = "" if reviewed else " · 검토 전 초안"
        gallery.append(f"<section><h2>{escape(issue['title'])}</h2><div class='cards'>")
        for number, (title, body, note) in enumerate(cards, 1):
            if reviewed:
                note = [
                    line.replace(
                        "검토 전 · 앱 공개 주소 연결 대기",
                        "원문과 날짜를 함께 읽는 기록",
                    ).replace("검토 전 · ", "")
                    for line in note
                ]
            stem = OUTPUT / asset / f"{asset}-{number:02}"
            render_card(stem, title, body, note, number, number in (1, 5), reviewed)
            gallery.append(
                f"<a href='{asset}/{asset}-{number:02}.png'><img src='{asset}/{asset}-{number:02}.png' alt='{escape(' '.join(title), quote=True)}{disclosure}' loading='lazy'></a>"
            )
        gallery.append("</div><p>" + escape(issue["summary"]) + "</p><ul>")
        for source in issue["sources"]:
            gallery.append(
                f"<li><a href='{escape(source['url'], quote=True)}'>{escape(source['publisher']+' · '+source['title'])}</a> — {escape(source['locator'])}</li>"
            )
        gallery.append("</ul></section>")
        caption = (
            (
                "원고 승인 · 공개 주소 연결·게시 당일 최신성 확인 대기\n\n"
                if reviewed
                else "게시 검토 전 초안 · 공개 주소 연결 대기\n\n"
            )
            + issue["title"]
            + "\n\n"
            + issue["summary"]
            + "\n\n"
            + "\n".join(issue["facts"])
            + "\n\n"
            + "\n".join(issue["unknowns"])
            + "\n\n출처\n"
            + "\n".join(
                source["publisher"] + " · " + source["title"] + "\n" + source["url"]
                for source in issue["sources"]
            )
            + "\n\n앱의 공개 주소가 확정되면 같은 사건의 해설로 연결합니다. 현재 푸시 알림 제공을 약속하지 않습니다.\n#나라의근황 #정치이슈 #정치쉽게보기 #의정의흐름\n"
        )
        (OUTPUT / asset / "caption.txt").write_text(caption)
        alt = [
            {
                "image": f"{asset}-{number:02}.png",
                "alt": "나라의 근황 · "
                + " ".join(title + body)
                + ("" if reviewed else " 게시 검토 전 초안."),
            }
            for number, (title, body, _) in enumerate(cards, 1)
        ]
        (OUTPUT / asset / "alt-text.json").write_text(
            json.dumps(alt, ensure_ascii=False, indent=2)
        )
        manifest.append(
            {
                "assetId": asset,
                "issueId": issue["id"],
                "images": 5,
                "status": (
                    "approved-awaiting-release"
                    if reviewed
                    else "draft-awaiting-human-review"
                ),
                "reviewedAt": reviewed_at,
                "approvalEvidence": issue.get("reviewEvidence") if reviewed else None,
                "publicUrl": None,
                "scheduled": False,
                "requiresFreshnessCheckAtPublication": True,
            }
        )
    (OUTPUT / "preview.html").write_text("".join(gallery) + "</main></html>")
    (OUTPUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2)
    )
    LOGGER.info(
        "Prepared %s original review cards in %s",
        sum(item["images"] for item in manifest),
        OUTPUT,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
