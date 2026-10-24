"""Package reviewed, digest-pinned runtime files without credentials or source data."""

import argparse
import hashlib
import logging
import re
import tarfile
from pathlib import Path

LOGGER = logging.getLogger(__name__)


def build(output: Path, images: dict[str, str], compose: Path, digest: str) -> None:
    """Verify executable bytes and include only an explicit release allowlist."""
    if output.exists() or not output.name.endswith(".tar.gz"):
        raise ValueError("a new tar.gz output is required")
    if (
        not compose.is_file()
        or hashlib.sha256(compose.read_bytes()).hexdigest() != digest
    ):
        raise ValueError("pinned ARM64 Compose checksum mismatch")
    for image in images.values():
        if not re.fullmatch(r"[A-Za-z0-9./:_-]+@sha256:[a-f0-9]{64}", image):
            raise ValueError("all images require immutable sha256 digests")
    root = Path(__file__).resolve().parents[1]
    configuration = (root / "compose.production.yml").read_text()
    for name, image in images.items():
        configuration = configuration.replace(
            f"${{{name}:?immutable digest required}}", image
        )
    with tarfile.open(output, "x:gz") as archive:
        import io

        rendered = configuration.encode()
        member = tarfile.TarInfo("compose.production.yml")
        member.size, member.mode = len(rendered), 0o644
        archive.addfile(member, io.BytesIO(rendered))
        executable = compose.read_bytes()
        binary = tarfile.TarInfo("bin/docker-compose")
        binary.size, binary.mode = len(executable), 0o755
        archive.addfile(binary, io.BytesIO(executable))
        for directory in ("scripts", "infra/systemd", "src/main/resources/sql"):
            for path in sorted((root / directory).rglob("*")):
                if path.is_file() and path.suffix in {
                    ".py",
                    ".sh",
                    ".sql",
                    ".service",
                    ".timer",
                }:
                    archive.add(
                        path, arcname=str(path.relative_to(root)), recursive=False
                    )
    LOGGER.info(
        "release packaged: %s sha256=%s",
        output,
        hashlib.sha256(output.read_bytes()).hexdigest(),
    )


def main() -> None:
    """Require operator-selected image and Compose versions; never upload or deploy."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("backend", "web", "worker", "mysql"):
        parser.add_argument(f"--{name}-image", required=True)
    parser.add_argument("--compose-binary", type=Path, required=True)
    parser.add_argument("--compose-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    build(
        args.output,
        {
            f"{name.upper()}_IMAGE": getattr(args, f"{name}_image")
            for name in ("backend", "web", "worker", "mysql")
        },
        args.compose_binary,
        args.compose_sha256,
    )


if __name__ == "__main__":
    main()
