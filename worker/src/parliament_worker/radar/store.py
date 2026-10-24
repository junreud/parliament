"""Idempotent observations and first-seen history for the news radar."""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from parliament_worker.radar.models import Article, iso


class RadarStore:
    """Persist URL identities and observations without turning retries into growth."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS articles(id TEXT PRIMARY KEY, title TEXT NOT NULL,
          url TEXT NOT NULL, publisher TEXT NOT NULL, published_at TEXT NOT NULL,
          first_seen TEXT NOT NULL, last_seen TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS observations(at TEXT PRIMARY KEY);
        """)

    def observe(self, items: list[Article], now: datetime) -> None:
        """Commit successful observations; repeated URLs keep their original first-seen time."""
        with self.db:
            for article in items:
                self.db.execute(
                    """INSERT INTO articles VALUES(?,?,?,?,?,?,?)
                  ON CONFLICT(id) DO UPDATE SET last_seen=excluded.last_seen""",
                    (
                        article.id,
                        article.title,
                        article.url,
                        article.publisher,
                        iso(article.published_at),
                        iso(now),
                        iso(now),
                    ),
                )
            self.db.execute("INSERT OR IGNORE INTO observations VALUES(?)", (iso(now),))

    def articles(self, now: datetime) -> list[Article]:
        """Read a bounded recent window; ignore old and future news."""
        return [
            Article(row[0], row[1], row[2], datetime.fromisoformat(row[3]))
            for row in self.db.execute(
                """SELECT title,url,publisher,published_at FROM articles
                  WHERE published_at>=? AND published_at<=? ORDER BY published_at DESC LIMIT 2000""",
                (iso(now - timedelta(hours=72)), iso(now + timedelta(minutes=5))),
            )
        ]

    def has_baseline(self, now: datetime) -> bool:
        """Require an actual observation covering the preceding 12-hour comparison."""
        row = self.db.execute("SELECT MIN(at) FROM observations").fetchone()
        return bool(row and row[0] and row[0] <= iso(now - timedelta(hours=12)))

    def first_seen(self) -> dict[str, datetime]:
        """Return observed first-seen times rather than using repeated fetch counts."""
        return {
            row[0]: datetime.fromisoformat(row[1])
            for row in self.db.execute("SELECT id,first_seen FROM articles")
        }

    def close(self) -> None:
        """Close the local history database."""
        self.db.close()
