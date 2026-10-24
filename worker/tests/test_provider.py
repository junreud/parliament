"""The real HTTP provider is exercised only against synthetic fake responses."""

import json
from dataclasses import replace
from decimal import Decimal

import httpx
import pytest
from test_processing import document

from parliament_worker.provider import OpenAISummaryProvider, TokenPrices
from parliament_worker.review import ReviewLedger, generate_draft, validate_draft
from parliament_worker.summaries import prepare_summary


def response_for(doc, *, wrong_citation=False, usage=True):
    payload = {
        "oneLine": "합성 안내가 발표되었다.",
        "claims": [
            {
                "text": "합성 안내가 발표되었다.",
                "evidenceId": "wrong" if wrong_citation else f"ev_{doc.identity}",
                "excerpt": doc.body,
                "sourceVersion": doc.payload_hash,
            }
        ],
    }
    result = {
        "id": "chatcmpl-synthetic",
        "model": "explicit-test-model-snapshot",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps(payload, ensure_ascii=False),
                    "refusal": None,
                },
            }
        ],
    }
    if usage:
        result["usage"] = {"prompt_tokens": 120, "completion_tokens": 60}
    return result


def provider(client, *, input_price="1000", output_price="2000"):
    return OpenAISummaryProvider(
        "fake-key",
        "explicit-test-model",
        TokenPrices(Decimal(input_price), Decimal(output_price)),
        enabled=True,
        client=client,
    )


def test_request_uses_fixed_official_api_schema_and_delimited_untrusted_source(now):
    doc = document(now)
    requests = []
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: requests.append(request)
            or httpx.Response(200, json=response_for(doc))
        )
    )
    draft = provider(client).generate(doc)
    request = requests[0]
    body = json.loads(request.content)
    assert str(request.url) == "https://api.openai.com/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer fake-key"
    assert (
        body["model"] == "explicit-test-model" and body["max_completion_tokens"] <= 1000
    )
    assert body["store"] is False and body["response_format"]["type"] == "json_schema"
    assert body["messages"][0]["role"] == "developer"
    assert "untrusted" in body["messages"][0]["content"].lower()
    assert (
        json.loads(body["messages"][1]["content"])["untrustedSource"]["sourceHash"]
        == doc.payload_hash
    )
    assert not validate_draft(draft, doc)
    assert draft.provenance.source_hash == doc.payload_hash
    assert draft.provenance.actual_model == "explicit-test-model-snapshot"
    assert draft.provenance.actual_cost_krw == Decimal("0.24")


@pytest.mark.parametrize("price", ["-1", "NaN", "Infinity", "0"])
def test_invalid_or_free_unconfigured_token_prices_are_rejected(price):
    with pytest.raises(ValueError, match="price"):
        TokenPrices(Decimal(price), Decimal("100"))


def test_env_requires_explicit_key_model_and_both_configured_prices(monkeypatch):
    for key in (
        "OPENAI_API_KEY",
        "PARLIAMENT_SUMMARY_MODEL",
        "PARLIAMENT_SUMMARY_INPUT_KRW_PER_MILLION",
        "PARLIAMENT_SUMMARY_OUTPUT_KRW_PER_MILLION",
    ):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ValueError):
        OpenAISummaryProvider.from_env()


def test_api_redirect_never_forwards_key_even_if_client_follows_redirects(now):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "https://evil.test"})

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    with pytest.raises(ValueError, match="redirect"):
        provider(client).generate(document(now))
    assert len(requests) == 1


def test_provider_response_size_is_bounded_before_json_parse(now):
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, content=b"x" * 200000)
        )
    )
    with pytest.raises(ValueError, match="size"):
        provider(client).generate(document(now))


def test_budget_is_reserved_before_http_and_settled_by_reported_token_usage(
    tmp_path, now
):
    doc = document(now)
    ledger = ReviewLedger(tmp_path / "ledger.sqlite3", monthly_budget=Decimal("100"))
    requests = []

    def handler(request):
        requests.append(request)
        assert ledger.available(now) < Decimal("100")
        return httpx.Response(200, json=response_for(doc))

    p = provider(httpx.Client(transport=httpx.MockTransport(handler)))
    draft, errors = generate_draft(p, doc, ledger, now)
    assert not errors and len(requests) == 1
    assert ledger.available(now) == Decimal("99.76")
    ledger.close()


def test_insufficient_budget_causes_no_paid_request(tmp_path, now):
    calls = []
    doc = document(now)
    ledger = ReviewLedger(tmp_path / "ledger.sqlite3", monthly_budget=Decimal("0.01"))
    p = provider(
        httpx.Client(
            transport=httpx.MockTransport(lambda request: calls.append(request))
        )
    )
    with pytest.raises(ValueError, match="budget"):
        generate_draft(p, doc, ledger, now)
    assert calls == []
    ledger.close()


def test_bad_citations_remain_blocked_and_source_model_versions_are_immutable(
    tmp_path, now
):
    doc = document(now)
    p = provider(
        httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200, json=response_for(doc, wrong_citation=True)
                )
            )
        )
    )
    ledger = ReviewLedger(tmp_path / "ledger.sqlite3", monthly_budget=Decimal("100"))
    path = prepare_summary(doc, p, ledger, tmp_path, now)
    stored = json.loads(path.read_text())
    assert (
        stored["status"] == "blocked"
        and "evidence_missing" in stored["validationErrors"]
    )
    assert stored["sourceHash"] == doc.payload_hash and stored["parserVersion"]
    assert stored["provider"]["model"] == "explicit-test-model-snapshot"
    assert stored["provider"]["inputKrwPerMillion"]
    assert stored["provider"]["outputKrwPerMillion"]
    assert stored["requiresHumanReview"] is True
    assert stored["draftHash"] in path.name
    assert not (tmp_path / "published").exists()
    ledger.close()


def test_missing_usage_keeps_conservative_reserved_cost(tmp_path, now):
    doc = document(now)
    p = provider(
        httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json=response_for(doc, usage=False))
            )
        )
    )
    ledger = ReviewLedger(tmp_path / "ledger.sqlite3", monthly_budget=Decimal("100"))
    reserved = p.estimate_krw(doc)
    draft, _ = generate_draft(p, doc, ledger, now)
    assert draft.provenance.actual_cost_krw is None
    assert ledger.available(now) == Decimal("100") - reserved
    ledger.close()


def test_restricted_source_cannot_be_sent_to_model(now):
    calls = []
    p = provider(
        httpx.Client(
            transport=httpx.MockTransport(lambda request: calls.append(request))
        )
    )
    with pytest.raises(ValueError, match="permission"):
        p.generate(replace(document(now), license_status="restricted"))
    assert not calls


def test_disclaimer_only_body_blocks_model_and_cost_before_reservation(
    tmp_path, now, fixture
):
    from parliament_worker.connectors import parse_detail, parse_listing

    item = parse_listing("korea", fixture("korea-list.html"))[0]
    doc = parse_detail("korea", item, fixture("korea-disclaimer-only.html"), now)
    calls = []
    p = provider(
        httpx.Client(
            transport=httpx.MockTransport(lambda request: calls.append(request))
        )
    )
    ledger = ReviewLedger(tmp_path / "ledger.sqlite3", monthly_budget=Decimal("100"))
    with pytest.raises(ValueError, match="body"):
        generate_draft(p, doc, ledger, now)
    assert not calls and ledger.available(now) == Decimal("100")
    assert (
        ledger.connection.execute("SELECT COUNT(*) FROM provider_requests").fetchone()[
            0
        ]
        == 0
    )
    with pytest.raises(ValueError, match="body"):
        p.generate(doc)
    assert not calls
    ledger.close()


def test_unavailable_body_blocks_protocol_estimation_before_cost(tmp_path, now):
    doc = replace(document(now), body="", title_locator=".view_title h1")

    class NeverCall:
        def estimate_krw(self, document):
            pytest.fail("metadata-only source must not reach provider estimation")

        def generate(self, document):
            pytest.fail("metadata-only source must not reach paid HTTP")

    ledger = ReviewLedger(tmp_path / "ledger.sqlite3", monthly_budget=Decimal("100"))
    with pytest.raises(ValueError, match="body"):
        generate_draft(NeverCall(), doc, ledger, now)
    assert ledger.available(now) == Decimal("100")
    assert (
        ledger.connection.execute("SELECT COUNT(*) FROM provider_requests").fetchone()[
            0
        ]
        == 0
    )
    ledger.close()


def test_uncited_one_line_and_unknown_response_fields_are_rejected(now):
    doc = document(now)
    result = response_for(doc)
    content = json.loads(result["choices"][0]["message"]["content"])
    content["oneLine"] = "unsupported separate claim"
    content["stage"] = "effective"
    result["choices"][0]["message"]["content"] = json.dumps(content)
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=result))
    )
    with pytest.raises(ValueError, match="structure"):
        provider(client).generate(doc)


def test_identical_source_model_prompt_uses_local_draft_without_recharging(
    tmp_path, now
):
    calls = []
    doc = document(now)

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=response_for(doc))

    p = provider(httpx.Client(transport=httpx.MockTransport(handler)))
    ledger = ReviewLedger(tmp_path / "ledger.sqlite3", monthly_budget=Decimal("100"))
    first = prepare_summary(doc, p, ledger, tmp_path, now)
    second = prepare_summary(doc, p, ledger, tmp_path, now)
    assert first == second and len(calls) == 1
    assert ledger.available(now) == Decimal("99.76")
    ledger.close()


def test_measured_overrun_is_recorded_and_blocks_future_cost_reservation(tmp_path, now):
    ledger = ReviewLedger(tmp_path / "ledger.sqlite3", monthly_budget=Decimal("10"))
    request = ledger.reserve_request(Decimal("5"), now)
    with pytest.raises(ValueError, match="exceeded"):
        ledger.settle_request(request, Decimal("11"))
    assert ledger.available(now) == Decimal("0")
    with pytest.raises(ValueError, match="budget"):
        ledger.reserve_request(Decimal("0.1"), now)
    ledger.close()


def test_estimate_overrun_stops_calls_even_when_monthly_budget_remains(tmp_path, now):
    ledger = ReviewLedger(tmp_path / "ledger.sqlite3", monthly_budget=Decimal("100"))
    request = ledger.reserve_request(Decimal("5"), now)
    with pytest.raises(ValueError, match="exceeded"):
        ledger.settle_request(request, Decimal("6"))
    assert ledger.available(now) == Decimal("94")
    with pytest.raises(ValueError, match="budget"):
        ledger.reserve_request(Decimal("1"), now)
    ledger.close()
