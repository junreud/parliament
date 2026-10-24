"""Read the local news shortlist separately from official GraphRAG evidence."""

import json
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


def _public_link(raw: Any) -> str | None:
    """Accept a normal HTTPS news link without userinfo or secret parameters."""
    if not isinstance(raw, str) or len(raw) > 2000:
        return None
    parsed = urlsplit(raw)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username:
        return None
    if any(
        part.split("=", 1)[0].lower() in {"key", "token", "apikey", "servicekey"}
        for part in parsed.query.split("&")
    ):
        return None
    return raw


def radar_summary(root: Path) -> dict[str, Any] | None:
    """Return headline candidates and exact local article counts when available."""
    state = root / ".local/radar/state.sqlite3"
    shortlist = root / ".local/radar/public.json"
    if not state.is_file() or not shortlist.is_file():
        return None
    try:
        with sqlite3.connect(state.as_uri() + "?mode=ro", uri=True, timeout=2) as db:
            db.execute("PRAGMA query_only=ON")
            articles = db.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
            observations = db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        public = json.loads(shortlist.read_text(encoding="utf-8"))
        items = []
        for item in public.get("items", [])[:20]:
            if not isinstance(item, dict):
                continue
            items.append(
                {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "reason": item.get("reason"),
                    "reviewStatus": item.get("reviewStatus"),
                    "articleCount": item.get("articleCount"),
                    "publisherCount": item.get("publisherCount"),
                    "articles": [
                        {
                            "title": article.get("title"),
                            "publisher": article.get("publisher"),
                            "publishedAt": article.get("publishedAt"),
                            "url": _public_link(article.get("url")),
                        }
                        for article in item.get("articles", [])[:20]
                        if isinstance(article, dict)
                    ],
                }
            )
        return {
            "classification": "news_shortlist_not_official_evidence",
            "generatedAt": public.get("generatedAt"),
            "status": public.get("status"),
            "articleRecords": articles,
            "observations": observations,
            "candidates": items,
        }
    except (OSError, ValueError, sqlite3.Error):
        return None
