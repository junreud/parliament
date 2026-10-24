"""Immutable content-addressed local raw versions and processing identity index."""

import json
import sqlite3
from pathlib import Path

from parliament_worker.models import SourceDocument


class LocalRawStore:
    """Write only beneath an explicitly selected output directory.

    Raw bytes and their first observation metadata are immutable. SQLite tracks
    source identity/version membership independently of filenames and titles.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(root / "raw-index.sqlite3")
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS raw_versions ("
            "sequence INTEGER PRIMARY KEY AUTOINCREMENT, identity TEXT NOT NULL, "
            "payload_hash TEXT NOT NULL, observed_at TEXT NOT NULL, "
            "UNIQUE(identity, payload_hash))"
        )
        self.connection.commit()

    def save(self, document: SourceDocument) -> Path:
        """Persist an original version without overwriting an earlier snapshot."""
        if not document.raw:
            raise ValueError("raw response required")
        directory = self.root / "raw" / document.identity
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{document.payload_hash}.bin"
        try:
            with path.open("xb") as handle:
                handle.write(document.raw)
        except FileExistsError:
            if path.read_bytes() != document.raw:
                raise ValueError("immutable raw version conflict")
        metadata = {
            "sourceKey": document.source_key,
            "recordKey": document.record_key,
            "sourceUrl": document.source_url,
            "payloadHash": document.payload_hash,
            "observedAt": document.collected_at.isoformat(),
            "publishedAt": (
                document.published_at.isoformat() if document.published_at else None
            ),
            "occurredAt": (
                document.occurred_at.isoformat() if document.occurred_at else None
            ),
            "agency": document.agency,
            "locator": document.locator,
            "bodyStatus": document.body_status,
            "titleLocator": document.title_locator,
            "licenseStatus": document.license_status,
            "attachments": [
                {"name": item.name, "sourceUrl": item.source_url, "status": item.status}
                for item in document.attachments
            ],
        }
        try:
            with path.with_suffix(".json").open("x", encoding="utf-8") as handle:
                json.dump(metadata, handle, ensure_ascii=False, indent=2)
        except FileExistsError:
            pass  # Preserve the first observation's exact metadata.
        self.connection.execute(
            "INSERT OR IGNORE INTO raw_versions(identity,payload_hash,observed_at) VALUES (?,?,?)",
            (
                document.identity,
                document.payload_hash,
                document.collected_at.isoformat(),
            ),
        )
        self.connection.commit()
        return path

    def version_count(self, identity: str) -> int:
        """Return the number of preserved versions of one original source ID."""
        row = self.connection.execute(
            "SELECT COUNT(*) FROM raw_versions WHERE identity=?", (identity,)
        ).fetchone()
        return int(row[0])

    def version_number(self, identity: str, payload_hash: str) -> int:
        """Return the stable ordinal of a version even when older versions replay."""
        row = self.connection.execute(
            "SELECT COUNT(*) FROM raw_versions WHERE identity=? AND sequence<="
            "(SELECT sequence FROM raw_versions WHERE identity=? AND payload_hash=?)",
            (identity, identity, payload_hash),
        ).fetchone()
        return int(row[0])

    def close(self) -> None:
        """Close the processing index connection."""
        self.connection.close()
