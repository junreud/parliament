"""Render the selected magazine system into private reel/Story review assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import subprocess
from html import escape
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
GROWTH = ROOT / "docs/marketing/beta-4w/growth"
SERIF = "/System/Library/Fonts/Supplemental/AppleMyungjo.ttf"
SANS = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
BG, FG, MUTED, ACCENT = "#141719", "#F3F0E8", "#B6B9B9", "#B17279"


def render_frame(frame: dict[str, Any], output: Path, number: int) -> None:
    """Render legible text within a conservative vertical-video UI safe area."""
    canvas = Image.new("RGB", (1080, 1920), BG)
    draw = ImageDraw.Draw(canvas)

    def text(
        lines: list[str],
        y: int,
        size: int,
        color: str = FG,
        serif: bool = False,
        step: int = 76,
    ) -> int:
        font = ImageFont.truetype(SERIF if serif else SANS, size)
        for line in lines:
            if font.getlength(line) > 840:
                raise ValueError(f"Text exceeds safe width: {line}")
            draw.text((96, y), line, font=font, fill=color, anchor="ls")
            y += step
        return y

    text(["나라의 근황"], 182, 43, serif=True)
    draw.line((96, 224, 940, 224), fill=MUTED, width=1)
    text([frame["label"]], 346, 30, MUTED)
    draw.rectangle((96, 394, 154, 399), fill=ACCENT)
    text(frame["title"], 572, 76, serif=True, step=112)
    # Wrap explanatory lines by measured font width, not character count.
    font = ImageFont.truetype(SANS, 40)
    wrapped = []
    for line in frame["body"]:
        current = ""
        for char in line:
            if font.getlength(current + char) > 840:
                wrapped.append(current)
                current = ""
            current += char
        wrapped.append(current)
    if len(wrapped) > 6:
        raise ValueError("Body exceeds six safe lines")
    text(wrapped, 966, 40, step=70)
    text([frame["source"]], 1474, 27, MUTED)
    draw.line((96, 1536, 940, 1536), fill=MUTED, width=1)
    text([f"@flow_goverment   ·   {number:02}"], 1594, 28, MUTED)
    canvas.save(output)


def srt_time(seconds: int) -> str:
    """Convert a bounded integer time to subtitle timing."""
    return f"00:{seconds // 60:02}:{seconds % 60:02},000"


def prepare_destination(root: Path, asset: str) -> Path:
    """Select a per-asset folder and protect any recorded approval version."""
    if not asset.isalnum():
        raise ValueError("asset identity must be alphanumeric")
    target = root / f"reel-{asset}"
    manifest = target / "manifest.json"
    if manifest.exists():
        previous = json.loads(manifest.read_text())
        if (
            previous.get("reviewed_at")
            or previous.get("status") != "draft_awaiting_human_review"
        ):
            raise ValueError("approved or non-draft output must be archived explicitly")
    target.mkdir(parents=True, exist_ok=True)
    return target


def main() -> None:
    """Export only private review artifacts; no approval or platform mutation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, default=GROWTH / "templates/reel.example.json"
    )
    parser.add_argument("--video", action="store_true")
    args = parser.parse_args()
    data = json.loads(args.input.read_text())
    frames = data["frames"]
    cursor = 0
    for frame in frames:
        if frame["start"] != cursor or frame["end"] <= frame["start"]:
            raise ValueError("Reel timing must be contiguous and increasing")
        cursor = frame["end"]
    if cursor != 30:
        raise ValueError("Initial reel must be exactly 30 seconds")
    destination = prepare_destination(GROWTH, data["asset_id"])
    folder = destination.name
    manifest = {
        "asset_id": data["asset_id"],
        "status": "draft_awaiting_human_review",
        "reviewed_at": None,
        "parent_asset_id": data["parent_asset_id"],
        "source_packet": data["source_packet"],
        "source_urls": data["source_urls"],
        "source_checked_at": data["source_checked_at"],
        "uncertainty": data["uncertainty"],
        "seconds": 30,
        "dimensions": [1080, 1920],
        "audio": "none; original graphics and burned-in captions",
        "files": [],
    }
    subtitles, concat = [], []
    previews = []
    for i, frame in enumerate(frames, 1):
        path = destination / f"frame-{i:02}.png"
        render_frame(frame, path, i)
        manifest["files"].append(
            {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        )
        subtitles.append(
            f"{i}\n{srt_time(frame['start'])} --> {srt_time(frame['end'])}\n"
            + "\n".join(frame["title"] + frame["body"])
        )
        concat += [f"file '{path.name}'", f"duration {frame['end'] - frame['start']}"]
        previews.append(Image.open(path).resize((270, 480)))
    concat.append(f"file 'frame-{len(frames):02}.png'")
    (destination / "frames.ffconcat").write_text("\n".join(concat) + "\n")
    (destination / "captions.srt").write_text("\n\n".join(subtitles) + "\n")
    caption = (
        data["title"]
        + "\n\n"
        + data["uncertainty"]
        + "\n\n출처: 대한민국헌법 제128~130조\n"
        + "\n".join(data["source_urls"])
        + "\n\n날짜와 조항을 함께 읽어 주세요.\n#나라의근황 #기록읽기 #개헌절차\n"
    )
    (destination / "caption.draft.txt").write_text(caption)
    (destination / "alt-text.txt").write_text(
        "얼굴·현장 영상 없이 헌법 개정의 제안, 공고, 국회 의결, 국민투표 절차를 명조 제목과 자막으로 설명하는 30초 영상. "
        + data["uncertainty"]
    )
    if args.video:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(destination / "frames.ffconcat"),
                "-f",
                "lavfi",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000",
                "-t",
                "30",
                "-r",
                "30",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-crf",
                "23",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(destination / "R01-review.mp4"),
            ],
            check=True,
        )
        path = destination / "R01-review.mp4"
        manifest["files"].append(
            {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        )
    stories = [
        {
            "label": "처음이라면 · 기록을 읽는 순서",
            "title": ["흘려본 정치 뉴스,", "어디부터 볼까요?"],
            "body": [
                "무슨 일인지 배경부터 읽고,",
                "확인된 사실과 주장을 나눈 뒤,",
                "날짜가 적힌 원문을 확인합니다.",
            ],
            "source": "특정 정당에 대한 찬반을 묻지 않습니다.",
        },
        {
            "label": "오늘의 편집 질문 · 실제 독자 질문 아님",
            "title": ["뉴스에서 가장", "헷갈리는 부분은?"],
            "body": [
                "발표와 시행은 어떻게 다를까?",
                "의견과 공식 결정은 어떻게 다를까?",
                "어려웠던 용어 하나를 남겨 주세요.",
            ],
            "source": "질문 스티커는 업로드 때 직접 추가합니다.",
        },
    ]
    for i, frame in enumerate(stories, 1):
        path = GROWTH / "stories" / f"story-{i:02}.png"
        render_frame(frame, path, i)
        previews.append(Image.open(path).resize((270, 480)))
    contact = Image.new("RGB", (270 * len(previews), 480), BG)
    for i, preview in enumerate(previews):
        contact.paste(preview, (i * 270, 0))
    contact.save(GROWTH / "contact-sheet.png")
    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )
    page = """<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>나라의 근황 · 성장 운영 검토실</title><style>:root{color-scheme:light}body{margin:0;background:#f3f0e8;color:#30383a;font:17px/1.7 system-ui}main{max-width:1200px;margin:auto;padding:32px}h1,h2{font-family:AppleMyungjo,serif}.notice{border-left:4px solid #7a4148;padding:16px;background:#fff}video{width:min(100%,324px);background:#141719}img{width:100%;height:auto}.grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px}a{color:#7a4148}.stories{max-width:600px;grid-template-columns:repeat(2,minmax(0,1fr))}@media(max-width:640px){main{padding:20px}.grid{grid-template-columns:repeat(2,minmax(0,1fr))}}button,a{min-height:44px}</style><main><h1>나라의 근황 · 성장 운영 검토실</h1><p class="notice">A 기록의 서재 · 새 릴스 1편과 스토리 2장은 사람 검토 대기입니다. 기존 카드 3편의 승인과 구분합니다. 예약·게시 상태는 콘텐츠 운영표와 실제 플랫폼 영수증으로 확인합니다.</p><p><a href="README.md">운영 안내</a> · <a href="reel-R01/caption.draft.txt">릴스 캡션</a> · <a href="reel-R01/manifest.json">출처·제작 상태</a></p><h2>R01 · 개헌 발언과 확정은 어떻게 다를까?</h2><video controls preload="metadata" poster="reel-R01/frame-01.png" aria-label="검토용 30초 개헌 절차 해설"><source src="reel-R01/R01-review.mp4" type="video/mp4"><track kind="subtitles" srclang="ko" label="한국어" src="reel-R01/captions.vtt"></video><p>30초 · 얼굴·음성 없이 그래픽과 화면 자막 · 원문 재확인 후 별도 승인 필요</p><div class="grid">"""
    for i, frame in enumerate(frames, 1):
        page += f'<a href="reel-R01/frame-{i:02}.png"><img src="reel-R01/frame-{i:02}.png" alt="{escape(" ".join(frame["title"]), quote=True)}"><span>{frame["start"]}–{frame["end"]}초</span></a>'
    page += '</div><h2>스토리 · 처음이라면 / 편집 질문</h2><p>발행 후 실제 게시물을 네이티브 공유하고 질문 스티커를 추가합니다. 아직 스토리가 게시되거나 독자 답변이 들어온 상태는 아닙니다.</p><div class="grid stories">'
    for i, frame in enumerate(stories, 1):
        page += f'<a href="stories/story-{i:02}.png"><img src="stories/story-{i:02}.png" alt="{escape(" ".join(frame["title"]), quote=True)}"></a>'
    page += "</div></main></html>"
    page = page.replace("reel-R01/", folder + "/")
    page = page.replace(
        "R01 · 개헌 발언과 확정은 어떻게 다를까?",
        escape(data["asset_id"] + " · " + data["title"]),
    )
    (GROWTH / "preview.html").write_text(page)
    (destination / "captions.vtt").write_text(
        "WEBVTT\n\n" + "\n\n".join(s.replace(",000", ".000") for s in subtitles) + "\n"
    )
    LOGGER.info("Prepared private reel and Story review assets in %s", GROWTH)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
