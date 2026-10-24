"""Exercise inference protocol safety without sending sources or secrets anywhere."""

import json

import httpx
import pytest

from parliament_worker.graphrag.client import (
    InferenceClient,
    InferenceConfig,
    InferenceError,
    canonical_body,
    parse_completion,
)

BASE = "https://inference.example.net/v1"
TOKEN = "synthetic-inference-token"


def config(base_url=BASE):
    return InferenceConfig(base_url, TOKEN)


def body(**changes):
    return {
        "model": "local-generator",
        "messages": [{"role": "user", "content": "공식 기록에서 관계를 찾으세요."}],
        "max_completion_tokens": 768,
        "stream": False,
        **changes,
    }


def completion(content='{"relations":[]} ', finish_reason="stop"):
    return {
        "choices": [{"finish_reason": finish_reason, "message": {"content": content}}]
    }


def test_same_request_recovery_sends_identical_bytes_and_pinned_root():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(202, json={"request_id": "job_123", "state": "queued"})

    client = InferenceClient(config(), transport=httpx.MockTransport(handler))
    first = body()
    reordered = dict(reversed(list(first.items())))
    assert client.submit(first, "graph-test-123")["request_id"] == "job_123"
    client.submit(reordered, "graph-test-123")
    assert requests[0].content == requests[1].content == canonical_body(first)
    assert b"\\uacf5" not in requests[0].content
    assert str(requests[0].url) == "https://inference.example.net/inference-jobs"
    assert requests[0].headers["Authorization"] == f"Bearer {TOKEN}"
    assert requests[0].headers["Idempotency-Key"] == "graph-test-123"
    assert requests[0].headers["Content-Type"] == "application/json"
    client.close()


@pytest.mark.parametrize("suffix", ["", "/", "/v1", "/v1/"])
def test_config_normalizes_sdk_prefix_exactly_once(suffix):
    value = config("https://inference.example.net" + suffix)
    assert value.root == "https://inference.example.net"
    assert value.base_url == BASE
    assert TOKEN not in repr(value)


@pytest.mark.parametrize(
    "url",
    [
        "http://inference.example.net/v1",
        "https://user:pass@inference.example.net/v1",
        "https://inference.example.net/v1?token=x",
        "https://inference.example.net/v1#fragment",
        "https://inference.example.net/v1/v1",
        "https://inference.example.net:8080/v1",
        "https://127.0.0.1/v1",
        "https://[::1]/v1",
        "https://169.254.169.254/v1",
        "https://localhost/v1",
        "https://worker.local/v1",
        "https://service.internal/v1",
        "https://inference.example.net\\@127.0.0.1/v1",
        " https://inference.example.net/v1",
    ],
)
def test_untrusted_or_internal_endpoint_is_rejected_before_http(url):
    with pytest.raises(InferenceError, match="configuration"):
        config(url)


def test_config_reads_distinct_inference_environment_without_factory_key(monkeypatch):
    monkeypatch.setenv("QWEN_BASE_URL", BASE)
    monkeypatch.setenv("QWEN_INFERENCE_TOKEN", TOKEN)
    monkeypatch.setenv("FACTORY_TOKEN", "do-not-use-factory-token")
    assert InferenceConfig.from_env() == config()
    monkeypatch.delenv("QWEN_INFERENCE_TOKEN")
    with pytest.raises(InferenceError, match="configuration"):
        InferenceConfig.from_env()


def test_models_poll_and_queue_use_fixed_paths_and_only_safe_model_metadata():
    requests = []

    def handler(request):
        requests.append(request)
        response = {
            "/v1/models": {
                "object": "list",
                "data": [{"id": "local-generator", "credential": TOKEN}],
                "actual_model": "RedHatAI/gemma-4-31B-it-NVFP4",
                "credential": TOKEN,
            },
            "/inference-jobs/job_123": {
                "request_id": "job_123",
                "state": "completed",
                "result": completion(),
            },
            "/inference-queue": {"queued": 0, "running": 1, "capacity": 2000},
        }[request.url.path]
        return httpx.Response(
            200,
            json=response,
            headers={"x-model-revision": "revision-123", "x-api-key": TOKEN},
        )

    client = InferenceClient(config(), transport=httpx.MockTransport(handler))
    models = client.models()
    assert models["data"][0]["id"] == "local-generator"
    assert models["actual_model"] == "RedHatAI/gemma-4-31B-it-NVFP4"
    assert models["_modelMetadata"]["revision"] == "revision-123"
    assert TOKEN not in json.dumps(models)
    assert parse_completion(client.poll("job_123")) == {"relations": []}
    assert client.queue()["capacity"] == 2000
    assert len(requests) == 3
    client.close()


@pytest.mark.parametrize("request_id", ["../secret", "a/b", "a?token=x", "", "x" * 129])
def test_poll_never_interprets_untrusted_request_ids_as_paths(request_id):
    requests = []
    client = InferenceClient(
        config(),
        transport=httpx.MockTransport(lambda request: requests.append(request)),
    )
    with pytest.raises(InferenceError, match="request_id"):
        client.poll(request_id)
    assert requests == []
    client.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"stream": True},
        {"model": "another-model"},
        {"reasoning_effort": "high"},
        {"tools": []},
        {"max_completion_tokens": 1025},
        {"max_completion_tokens": True},
        {"max_completion_tokens": 0},
        {"max_tokens": 256},
        {"messages": [{"role": "user", "content": "x" * (64 * 1024)}]},
        {"messages": [{"role": "tool", "content": "x"}]},
        {"messages": []},
        {"temperature": float("nan")},
    ],
)
def test_unsupported_or_oversized_request_never_reaches_server(changes):
    requests = []
    client = InferenceClient(
        config(),
        transport=httpx.MockTransport(lambda request: requests.append(request)),
    )
    with pytest.raises(InferenceError, match="request"):
        client.submit(body(**changes), "graph-test-123")
    assert requests == []
    client.close()


def test_provider_preflights_long_korean_request_without_uncertain_acceptance():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(400, json={"error": {"code": "context_limit"}})

    client = InferenceClient(config(), transport=httpx.MockTransport(handler))
    with pytest.raises(InferenceError) as captured:
        client.submit(
            body(messages=[{"role": "user", "content": "양육비 " * 750}]),
            "graph-test-long",
        )

    assert captured.value.status == 400
    assert captured.value.uncertain is False
    assert captured.value.retryable is False
    assert len(requests) == 1
    client.close()


def test_submission_requires_stable_safe_idempotency_key():
    client = InferenceClient(
        config(), transport=httpx.MockTransport(lambda _: httpx.Response(202))
    )
    for key in ("", "key\r\nx-secret: bad", "x" * 129):
        with pytest.raises(InferenceError, match="idempotency"):
            client.submit(body(), key)
    client.close()


@pytest.mark.parametrize(
    "status,retryable,uncertain",
    [
        (400, False, False),
        (401, False, False),
        (403, False, False),
        (404, False, False),
        (409, False, False),
        (413, False, False),
        (422, False, False),
        (429, True, False),
        (503, True, False),
        (504, True, True),
        (502, True, True),
    ],
)
def test_failures_are_categorized_without_automatic_retry_or_server_text(
    status, retryable, uncertain
):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            status, text=f"private error {TOKEN}", headers={"Retry-After": "7"}
        )

    client = InferenceClient(config(), transport=httpx.MockTransport(handler))
    with pytest.raises(InferenceError) as caught:
        client.submit(body(), "graph-test-123")
    error = caught.value
    assert (error.status, error.retryable, error.uncertain) == (
        status,
        retryable,
        uncertain,
    )
    assert error.retry_after == 7
    assert TOKEN not in str(error) and "private error" not in str(error)
    assert len(requests) == 1
    client.close()


def test_transport_loss_preserves_uncertainty_without_retry():
    requests = []

    def handler(request):
        requests.append(request)
        raise httpx.ReadTimeout(f"private {TOKEN}", request=request)

    client = InferenceClient(config(), transport=httpx.MockTransport(handler))
    with pytest.raises(InferenceError) as caught:
        client.submit(body(), "graph-test-123")
    assert caught.value.uncertain and caught.value.retryable
    assert TOKEN not in str(caught.value)
    assert len(requests) == 1
    client.close()


def test_authentication_redirect_is_never_followed():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(307, headers={"Location": "https://evil.example.net"})

    client = InferenceClient(config(), transport=httpx.MockTransport(handler))
    with pytest.raises(InferenceError, match="redirect"):
        client.submit(body(), "graph-test-123")
    assert len(requests) == 1
    client.close()


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(202, content=b"x" * (1024 * 1024 + 1)),
        httpx.Response(202, content=b'{"request_id":"a","request_id":"b"}'),
        httpx.Response(202, text="<html>Cloudflare timeout</html>"),
        httpx.Response(202, json=["invalid"]),
        httpx.Response(202, json={"request_id": "../bad", "state": "queued"}),
    ],
)
def test_invalid_acceptance_response_remains_uncertain_and_bounded(response):
    client = InferenceClient(
        config(), transport=httpx.MockTransport(lambda _: response)
    )
    with pytest.raises(InferenceError) as caught:
        client.submit(body(), "graph-test-123")
    assert caught.value.uncertain
    client.close()


@pytest.mark.parametrize(
    "payload",
    [
        completion('{"role":"speaker"}', "length"),
        completion('```json\n{"role":"speaker"}\n```'),
        completion('{"role":"speaker","role":"voter"}'),
        completion('[{"role":"speaker"}]'),
        completion('{"confidence":NaN}'),
        completion("x" * 4097),
        {"choices": [{"finish_reason": "stop", "message": {"reasoning": "{}"}}]},
        {"state": "running", "result": completion()},
    ],
)
def test_truncated_unstructured_or_contradictory_completion_is_not_graph_data(payload):
    with pytest.raises(InferenceError, match="completion"):
        parse_completion(payload)


def test_completion_accepts_only_finished_json_and_ignores_thinking():
    value = completion('{"relations":[]}')
    value["choices"][0]["message"]["reasoning"] = "do not store this reasoning"
    assert parse_completion(value) == {"relations": []}
    assert parse_completion({"state": "completed", "result": value}) == {
        "relations": []
    }


def test_ambiguous_success_can_be_recovered_with_original_intent():
    client = InferenceClient(
        config(),
        transport=httpx.MockTransport(lambda _: httpx.Response(202, text="bad")),
    )
    with pytest.raises(InferenceError) as caught:
        client.submit(body(), "graph-test-123")
    assert caught.value.uncertain and caught.value.retryable
    client.close()


def test_request_json_limit_covers_optional_fields_outside_messages():
    client = InferenceClient(
        config(), transport=httpx.MockTransport(lambda _: httpx.Response(202))
    )
    with pytest.raises(InferenceError, match="request_size"):
        client.submit(body(response_format={"schema": "x" * 65536}), "graph-test-123")
    client.close()


def test_model_catalog_exposes_alias_actual_model_and_context_limit():
    client = InferenceClient(
        config(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "local-generator",
                            "root": "RedHatAI/gemma-4-31B-it-NVFP4",
                            "max_model_len": 4096,
                            "permission": [{"secret": TOKEN}],
                        }
                    ]
                },
            )
        ),
    )
    assert client.models()["data"] == [
        {
            "id": "local-generator",
            "root": "RedHatAI/gemma-4-31B-it-NVFP4",
            "max_model_len": 4096,
        }
    ]
    client.close()


def test_dns_resolution_blocks_private_answers_before_authorization(monkeypatch):
    client = InferenceClient(config())
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", ("10.0.0.7", 443))],
    )
    requests = []
    monkeypatch.setattr(
        client._client, "stream", lambda *_args, **_kwargs: requests.append(1)
    )
    with pytest.raises(InferenceError, match="private_address"):
        client.queue()
    assert requests == []
    client.close()


@pytest.mark.parametrize("path", ["/inference-jobs", "/inference-jobs/job_123"])
def test_queue_envelope_model_metadata_is_whitelisted_without_echoed_secrets(path):
    client = InferenceClient(
        config(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                202 if path == "/inference-jobs" else 200,
                json={
                    "request_id": "job_123",
                    "state": "completed",
                    "result": completion(),
                    "response_headers": {
                        "X-Inference-Request-Id": "job_123",
                        "X-Model-Repo": "RedHatAI/gemma-4-31B-it-NVFP4",
                        "X-Model-Revision": "5df75ccad9b74546f5be758a2a68acc2e16bbc9b",
                        "Authorization": f"Bearer {TOKEN}",
                        "X-Echo-Secret": TOKEN,
                        "X-Arbitrary-Json": {"token": TOKEN},
                    },
                    "_modelMetadata": {"injected_secret": TOKEN},
                },
            )
        ),
    )
    result = (
        client.submit(body(), "graph-test-123")
        if path == "/inference-jobs"
        else client.poll("job_123")
    )
    assert result["_modelMetadata"] == {
        "actual_model": "RedHatAI/gemma-4-31B-it-NVFP4",
        "revision": "5df75ccad9b74546f5be758a2a68acc2e16bbc9b",
    }
    assert "response_headers" not in result
    assert TOKEN not in json.dumps(result)
    client.close()


def test_http_model_repo_header_is_recognized_without_body_metadata():
    client = InferenceClient(
        config(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={"queued": 0},
                headers={"X-Model-Repo": "RedHatAI/gemma-4-31B-it-NVFP4"},
            )
        ),
    )
    assert client.queue()["_modelMetadata"] == {
        "actual_model": "RedHatAI/gemma-4-31B-it-NVFP4"
    }
    client.close()
