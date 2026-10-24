"""Editorial recommendations require fixed official evidence, not an article link."""

from pathlib import Path

import pytest

from parliament_worker.radar.review import preserve_evidence


def test_preserve_official_evidence_binds_url_hash_and_locator(tmp_path: Path):
    record = preserve_evidence(
        tmp_path,
        "https://www.president.go.kr/speeches/example",
        b"<p>official statement</p>",
        "2026-10-17T08:00:00Z",
        "p: statement",
        "발표 사실만 확인",
    )
    assert (
        tmp_path / (record["sha256"] + ".bin")
    ).read_bytes() == b"<p>official statement</p>"
    assert record["scope"] == "발표 사실만 확인"
    with pytest.raises(ValueError):
        preserve_evidence(
            tmp_path,
            "https://evil.example/",
            b"x",
            "2026-10-17T08:00:00Z",
            "p",
            "claim",
        )
    with pytest.raises(ValueError):
        preserve_evidence(
            tmp_path,
            "https://www.president.go.kr/a",
            b"x",
            "2026-10-17T08:00:00Z",
            "",
            "claim",
        )
