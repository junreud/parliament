"""Reject private runtime inputs and generated artifacts in the Git index."""

import logging
import subprocess
from pathlib import Path, PurePosixPath

LOGGER = logging.getLogger(__name__)
PRIVATE_COMPONENTS = {
    ".local",
    ".venv",
    ".terraform",
    "node_modules",
    "artifacts",
    "graphify-out",
    "playwright-report",
    "test-results",
    "__pycache__",
}
PRIVATE_INPUTS = {
    "src/main/resources/knowledge/issue-readings.json",
    "web/src/data/editorial-issues.json",
    "mobile/src/data/radar.json",
}
PUBLIC_DOCS = {
    "docs/README.md",
    "docs/parliament-ingestion.md",
    "docs/product/development-guidelines.md",
    "docs/product/editorial-policy.md",
}
PRIVATE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".db"}


def prohibited_path(name: str) -> bool:
    """Return whether a Git path belongs outside the public source repository.

    Args:
        name: POSIX path relative to the repository root.

    Returns:
        Whether the path is a credential, private input, or generated artifact.
    """
    path = PurePosixPath(name)
    if any(part in PRIVATE_COMPONENTS for part in path.parts):
        return True
    if path.name.startswith(".env") and path.name != ".env.example":
        return True
    if path.suffix.lower() in PRIVATE_SUFFIXES or ".sqlite" in path.name.lower():
        return True
    if name in PRIVATE_INPUTS or name.startswith("worker/manifests/"):
        return True
    return name.startswith("docs/") and not (
        name in PUBLIC_DOCS or name.startswith("docs/development/")
    )


def main() -> int:
    """Check the tracked index without reading or logging private file contents."""
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True
    )
    blocked = [
        name
        for name in result.stdout.decode().split("\0")
        if name and prohibited_path(name)
    ]
    for name in blocked:
        LOGGER.error("Private/generated path is tracked: %s", name)
    if not blocked:
        LOGGER.info("Public repository path boundary passed")
    return int(bool(blocked))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    raise SystemExit(main())
