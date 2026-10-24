"""Explicit authenticated import into one configured backend; redirects refused."""

import os
from typing import Any
from urllib.parse import urlsplit

import httpx


class BackendPublisher:
    """Import structural candidates as backend drafts, never approve explanations."""

    def __init__(
        self,
        base_url: str,
        admin_key: str,
        *,
        enabled: bool = False,
        client: httpx.Client | None = None,
    ) -> None:
        if not enabled:
            raise ValueError("backend import requires explicit opt-in")
        parts = urlsplit(base_url)
        local = parts.hostname in ("127.0.0.1", "localhost", "::1")
        if (
            (parts.scheme != "https" and not (local and parts.scheme == "http"))
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
            or parts.path not in ("", "/")
        ):
            raise ValueError("invalid fixed backend URL")
        if not admin_key or not admin_key.strip():
            raise ValueError("backend admin key required")
        self.endpoint = base_url.rstrip("/") + "/admin/tracking/events"
        self._admin_key = admin_key
        self.client = client or httpx.Client(follow_redirects=False, timeout=10.0)

    @classmethod
    def from_env(cls) -> "BackendPublisher":
        """Load the trusted fixed destination and secret from environment only."""
        key = os.environ.get("TRACKING_ADMIN_KEY") or os.environ.get(
            "PARLIAMENT_INGESTION_ADMIN_KEY", ""
        )
        return cls(
            os.environ.get("PARLIAMENT_BACKEND_URL", "http://127.0.0.1:8080"),
            key,
            enabled=True,
        )

    def publish(self, event: dict[str, Any]) -> dict[str, Any]:
        """Import one null-summary structural event into the backend review queue."""
        if event.get("summary") is not None:
            raise ValueError("generated summaries require manual review")
        response = self.client.post(
            self.endpoint,
            json=event,
            headers={"X-Parliament-Ingestion-Key": self._admin_key},
            follow_redirects=False,
        )
        if response.is_redirect:
            raise ValueError("backend auth redirect refused")
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        """Close backend connections without logging credentials."""
        self.client.close()
