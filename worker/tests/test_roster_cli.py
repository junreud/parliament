"""Import resumption preserves acknowledgements without treating replay as conflict."""

import json
from pathlib import Path
from unittest.mock import patch

import truststore

from parliament_worker.roster import cli
from parliament_worker.roster.cli import _save_import_receipt


def test_import_resume_keeps_original_receipt_and_records_replay(tmp_path: Path):
    path = tmp_path / "batch.json.receipt.json"
    original = {"id": "batch", "state": "draft", "replayed": False}
    replay = original | {"replayed": True}
    _save_import_receipt(path, original)
    _save_import_receipt(path, replay)
    _save_import_receipt(path, replay)
    assert json.loads(path.read_text()) == original
    snapshots = list(tmp_path.glob("*.replay-*.json"))
    assert len(snapshots) == 1
    assert json.loads(snapshots[0].read_text()) == replay


def test_import_resume_preserves_changed_review_state(tmp_path: Path):
    path = tmp_path / "batch.json.receipt.json"
    _save_import_receipt(path, {"id": "batch", "state": "draft"})
    _save_import_receipt(path, {"id": "batch", "state": "rejected"})
    snapshots = list(tmp_path.glob("*.replay-*.json"))
    assert json.loads(snapshots[0].read_text())["state"] == "rejected"


def test_official_source_client_uses_macos_native_trust(monkeypatch) -> None:
    """System validation can complete a server's missing intermediate chain."""
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    with patch.object(cli.httpx, "Client") as client:
        cli._official_source_client()
    assert isinstance(client.call_args.kwargs["verify"], truststore.SSLContext)


def test_official_source_client_preserves_explicit_ca(monkeypatch) -> None:
    """Deployment-configured certificate bundles keep their existing behavior."""
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    monkeypatch.setenv("SSL_CERT_FILE", "/configured/company-ca.pem")
    with patch.object(cli.httpx, "Client") as client:
        cli._official_source_client()
    assert "verify" not in client.call_args.kwargs
