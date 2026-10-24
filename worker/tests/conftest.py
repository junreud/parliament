"""All bundled records are synthetic and do not assert actual government events."""

from datetime import datetime
from pathlib import Path

import pytest


@pytest.fixture
def now():
    return datetime.fromisoformat("2026-10-07T12:00:00+09:00")


@pytest.fixture
def fixture():
    return lambda name: (Path(__file__).parent / "fixtures" / name).read_bytes()
