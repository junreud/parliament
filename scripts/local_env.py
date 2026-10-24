"""Generate local-only development secrets without modifying existing configuration."""

import os
import secrets
from pathlib import Path


def main() -> None:
    """Create a private .env only when none exists."""
    destination = Path(__file__).resolve().parents[1] / ".env"
    content = "\n".join(
        [
            f"PARLIAMENT_DB_PASSWORD={secrets.token_urlsafe(32)}",
            f"PARLIAMENT_DB_ROOT_PASSWORD={secrets.token_urlsafe(32)}",
            f"PARLIAMENT_INGESTION_ADMIN_KEY={secrets.token_urlsafe(32)}",
            f"TRACKING_ADMIN_KEY={secrets.token_urlsafe(32)}",
            "TRACKING_ENABLED=true",
            "TRACKING_PUBLIC_BASE_URL=http://localhost:3000",
            "PARLIAMENT_INGESTION_ENABLED=false",
            "PARLIAMENT_INGESTION_WRITE_ENABLED=false",
            "PARLIAMENT_AUTOMATIC_SYNC_ENABLED=false",
            "",
        ]
    )
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as target:
        target.write(content)


if __name__ == "__main__":
    main()
