"""CLI defaults are read-only; output/publishing/cloud writes are explicit."""

import json

import pytest
from test_processing import document

from parliament_worker.cli import main
from parliament_worker.models import CollectionResult
from parliament_worker.review import Claim, ReviewLedger, SummaryDraft, generate_draft


def test_cli_default_dry_run_does_not_create_output(monkeypatch, tmp_path, now):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "parliament_worker.cli.collect",
        lambda *args, **kwargs: CollectionResult(documents=[document(now)]),
    )
    assert main(["collect", "--source", "korea"]) == 0
    assert not list(tmp_path.iterdir())


def test_cli_explicit_output_writes_raw_and_event_contract(monkeypatch, tmp_path, now):
    monkeypatch.setattr(
        "parliament_worker.cli.collect",
        lambda *args, **kwargs: CollectionResult(documents=[document(now)]),
    )
    assert main(["collect", "--source", "korea", "--output", str(tmp_path)]) == 0
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["events"][0]["summary"] is None
    assert list((tmp_path / "raw").rglob("*.bin"))


def test_publish_requires_output_and_env_key_before_network(monkeypatch):
    monkeypatch.delenv("PARLIAMENT_TRACKING_ADMIN_KEY", raising=False)
    with pytest.raises(SystemExit):
        main(["collect", "--source", "korea", "--publish"])


def test_optional_provider_never_bypasses_budget_or_review(tmp_path, now):
    from decimal import Decimal

    called = []
    doc = document(now)

    class Provider:
        def estimate_krw(self, document):
            return Decimal("10")

        def generate(self, document):
            called.append(document.identity)
            return SummaryDraft(
                "[합성] 초안",
                [Claim("안내", f"ev_{document.identity}", doc.body, doc.payload_hash)],
            )

    ledger = ReviewLedger(tmp_path / "ledger.sqlite3", monthly_budget=Decimal("10"))
    draft, errors = generate_draft(Provider(), doc, ledger, now)
    assert not errors and draft.one_line and len(called) == 1
    with pytest.raises(ValueError, match="budget"):
        generate_draft(Provider(), doc, ledger, now)
    assert len(called) == 1
    ledger.close()


def test_prepare_summary_requires_output_and_cannot_mix_with_publish(
    monkeypatch, tmp_path
):
    with pytest.raises(SystemExit):
        main(["collect", "--source", "korea", "--prepare-summary"])
    with pytest.raises(SystemExit):
        main(
            [
                "collect",
                "--source",
                "korea",
                "--output",
                str(tmp_path),
                "--prepare-summary",
                "--publish",
            ]
        )


def test_explicit_summary_cli_only_writes_local_review_draft(
    monkeypatch, tmp_path, now
):
    import httpx
    from test_provider import provider, response_for

    from parliament_worker.provider import OpenAISummaryProvider

    monkeypatch.setenv(
        "PARLIAMENT_REVIEW_LEDGER", str(tmp_path / "shared-review.sqlite3")
    )
    monkeypatch.setattr(
        "parliament_worker.cli.collect",
        lambda *args, **kwargs: CollectionResult(documents=[document(now)]),
    )
    p = provider(
        httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json=response_for(document(now)))
            )
        )
    )
    monkeypatch.setattr(OpenAISummaryProvider, "from_env", classmethod(lambda cls: p))
    assert (
        main(
            [
                "collect",
                "--source",
                "korea",
                "--output",
                str(tmp_path),
                "--prepare-summary",
            ]
        )
        == 0
    )
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["events"][0]["summary"] is None
    assert report["summaryDrafts"] and report["importedDrafts"] == 0


def test_prepare_summary_requires_shared_ledger_before_provider(monkeypatch, tmp_path):
    from parliament_worker.provider import OpenAISummaryProvider

    monkeypatch.delenv("PARLIAMENT_REVIEW_LEDGER", raising=False)
    monkeypatch.setattr(
        OpenAISummaryProvider,
        "from_env",
        classmethod(lambda cls: pytest.fail("shared ledger must be required first")),
    )
    with pytest.raises(SystemExit):
        main(
            [
                "collect",
                "--source",
                "korea",
                "--output",
                str(tmp_path),
                "--prepare-summary",
            ]
        )


def test_different_sources_and_output_dirs_share_one_monthly_budget(
    monkeypatch, tmp_path, now
):
    from dataclasses import replace
    from decimal import Decimal

    import httpx
    from test_provider import provider, response_for

    from parliament_worker.provider import OpenAISummaryProvider

    ledger_path = tmp_path / "shared-review.sqlite3"
    monkeypatch.setenv("PARLIAMENT_REVIEW_LEDGER", str(ledger_path))
    monkeypatch.setenv("PARLIAMENT_SUMMARY_MONTHLY_BUDGET_KRW", "10")
    calls = []

    def source(name, *args, **kwargs):
        return CollectionResult(documents=[replace(document(now), source_key=name)])

    def configured():
        doc = replace(document(now), source_key="korea")

        def handler(request):
            calls.append(request)
            return httpx.Response(200, json=response_for(doc))

        result = provider(httpx.Client(transport=httpx.MockTransport(handler)))
        result.estimate_krw = lambda _: Decimal("10")
        return result

    monkeypatch.setattr("parliament_worker.cli.collect", source)
    monkeypatch.setattr(
        OpenAISummaryProvider, "from_env", classmethod(lambda cls: configured())
    )
    for index, source_name in enumerate(("korea", "opm")):
        result = main(
            [
                "collect",
                "--source",
                source_name,
                "--output",
                str(tmp_path / source_name),
                "--prepare-summary",
            ]
        )
        assert result == index
    assert len(calls) == 1
    ledger = ReviewLedger(ledger_path, monthly_budget=Decimal("10"))
    assert ledger.available(now) == Decimal("9.76")
    ledger.close()


def test_mail_cli_defaults_to_private_preview_without_ses(monkeypatch, tmp_path, now):
    from test_mail import BASE
    from test_mail_db import FakeConnection

    db = FakeConnection(now)
    db.close = lambda: None
    monkeypatch.setenv("TRACKING_PUBLIC_BASE_URL", BASE)
    monkeypatch.setattr("parliament_worker.db.connect_mysql", lambda: db)
    monkeypatch.setattr(
        "parliament_worker.mail.SesMailer",
        lambda **kwargs: pytest.fail("default CLI must not construct an SES client"),
    )
    assert main(["mail", "--output", str(tmp_path / "private")]) == 0
    assert db.mail["status"] == "queued"
    assert len(list((tmp_path / "private").glob("*.eml"))) == 1


def test_mail_send_requires_configured_sender_before_db_or_aws(monkeypatch, tmp_path):
    monkeypatch.delenv("PARLIAMENT_MAIL_FROM", raising=False)
    monkeypatch.setattr(
        "parliament_worker.db.connect_mysql",
        lambda: pytest.fail("sender configuration must be checked before DB"),
    )
    with pytest.raises(SystemExit):
        main(["mail", "--output", str(tmp_path), "--send"])


def test_operational_database_errors_log_only_category(monkeypatch, tmp_path, caplog):
    class SyntheticDatabaseError(Exception):
        pass

    def fail():
        raise SyntheticDatabaseError("private email and token must not be logged")

    monkeypatch.setattr("parliament_worker.db.connect_mysql", fail)
    assert main(["mail", "--output", str(tmp_path)]) == 1
    assert "SyntheticDatabaseError" in caplog.text
    assert "test_cli.py:" in caplog.text
    assert ":fail" in caplog.text
    assert "private email and token" not in caplog.text


def test_publish_and_s3_only_import_structural_drafts_with_preserved_raw(
    monkeypatch, tmp_path, now
):
    from dataclasses import replace

    from parliament_worker.provider import OpenAISummaryProvider

    documents = [
        document(now),
        replace(document(now), record_key="restricted", license_status="restricted"),
        replace(document(now), record_key="missing-date", published_at=None),
    ]
    imported, saved = [], []
    monkeypatch.setenv("TRACKING_ADMIN_KEY", "synthetic-admin-key")
    monkeypatch.setenv("PARLIAMENT_RAW_BUCKET", "synthetic-private-bucket")
    monkeypatch.setattr(
        "parliament_worker.cli.collect",
        lambda *args, **kwargs: CollectionResult(documents=documents),
    )
    monkeypatch.setattr(
        OpenAISummaryProvider,
        "from_env",
        classmethod(
            lambda cls: pytest.fail("--publish must not invoke model provider")
        ),
    )

    class FakePublisher:
        def publish(self, event):
            assert list((tmp_path / "raw").rglob("*.bin"))
            assert event["summary"] is None
            imported.append(event)

        def close(self):
            pass

    class FakeS3:
        def __init__(self, bucket, *, enabled):
            assert bucket == "synthetic-private-bucket" and enabled

        def save(self, source, record, raw):
            saved.append((source, record, raw))

    monkeypatch.setattr(
        "parliament_worker.cli.BackendPublisher.from_env", lambda: FakePublisher()
    )
    monkeypatch.setattr("parliament_worker.aws.S3RawStore", FakeS3)
    assert (
        main(
            [
                "collect",
                "--source",
                "korea",
                "--output",
                str(tmp_path),
                "--publish",
                "--s3",
            ]
        )
        == 0
    )
    report = json.loads((tmp_path / "report.json").read_text())
    assert len(imported) == 1 and report["importedDrafts"] == 1
    assert len(saved) == 3 and len(report["reviewQueue"]) == 2
    assert not report["summaryDrafts"]


def test_summary_cli_keeps_metadata_events_but_skips_disclaimer_model_calls(
    monkeypatch, tmp_path, now, fixture
):
    from decimal import Decimal

    from parliament_worker.connectors import parse_detail, parse_listing
    from parliament_worker.provider import OpenAISummaryProvider

    doc = parse_detail(
        "korea",
        parse_listing("korea", fixture("korea-list.html"))[0],
        fixture("korea-disclaimer-only.html"),
        now,
    )

    class NoModel:
        def close(self):
            pass

        def cache_key(self, document):
            pytest.fail("metadata-only source must be skipped before model calls")

    shared = tmp_path / "shared-review.sqlite3"
    monkeypatch.setenv("PARLIAMENT_REVIEW_LEDGER", str(shared))
    monkeypatch.setattr(
        OpenAISummaryProvider, "from_env", classmethod(lambda cls: NoModel())
    )
    monkeypatch.setattr(
        "parliament_worker.cli.collect",
        lambda *args, **kwargs: CollectionResult(documents=[doc]),
    )
    output = tmp_path / "korea"
    assert (
        main(
            [
                "collect",
                "--source",
                "korea",
                "--output",
                str(output),
                "--prepare-summary",
            ]
        )
        == 0
    )
    report = json.loads((output / "report.json").read_text())
    assert len(report["events"]) == 1 and report["events"][0]["summary"] is None
    assert report["events"][0]["evidence"][0]["locator"] == ".view_title h1"
    assert (
        report["reviewQueue"][0]["scope"] == "summary" and not report["summaryDrafts"]
    )
    ledger = ReviewLedger(shared, monthly_budget=Decimal("100000"))
    assert ledger.available(now) == Decimal("100000")
    assert (
        ledger.connection.execute("SELECT COUNT(*) FROM provider_requests").fetchone()[
            0
        ]
        == 0
    )
    ledger.close()
