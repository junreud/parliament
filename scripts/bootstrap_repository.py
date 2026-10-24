"""Initialize a clean clone with examples without overwriting operator inputs."""

import logging
from pathlib import Path

LOGGER = logging.getLogger(__name__)
SEEDS = (
    (
        "src/main/resources/knowledge/issue-readings.example.json",
        "src/main/resources/knowledge/issue-readings.json",
    ),
    (
        "web/src/data/editorial-issues.example.json",
        "web/src/data/editorial-issues.json",
    ),
    ("mobile/src/data/radar.example.json", "mobile/src/data/radar.json"),
)


def initialize(root: Path) -> list[Path]:
    """Copy missing example inputs, preserving every existing destination.

    Args:
        root: Repository root containing the versioned examples.

    Returns:
        Runtime input paths created by this invocation.
    """
    created = []
    for source, destination in SEEDS:
        target = root / destination
        if target.exists():
            continue
        data = (root / source).read_bytes()
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("xb") as stream:
                stream.write(data)
        except FileExistsError:
            continue
        created.append(target)
    return created


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    for path in initialize(Path(__file__).resolve().parents[1]):
        LOGGER.info("Initialized example input: %s", path.name)
