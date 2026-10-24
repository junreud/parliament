"""Exercise the private operator API with actual durable state and loopback HTTP."""

import importlib
import json
import socket
import sys
import threading
from types import ModuleType

import httpx
import pytest

from parliament_worker.graphrag.prompts import GROUP_ID_VERSION
from parliament_worker.graphrag.store import GraphStore

TOKEN = "synthetic-operator-key-0123456789abcdef"  # gitleaks:allow -- test-only synthetic key


@pytest.fixture
def api_module():
    try:
        return importlib.import_module("parliament_worker.graphrag.api")
    except ImportError:
        pytest.fail("The private GraphRAG operator API has not been implemented")


@pytest.fixture
def operator(api_module, tmp_path, monkeypatch):
    from parliament_worker.graphrag.index import current_artifacts

    monkeypatch.delenv("QWEN_INFERENCE_TOKEN", raising=False)
    store = GraphStore(tmp_path / "state")
    graph = ModuleType("parliament_worker.graphrag.index")
    query = ModuleType("parliament_worker.graphrag.query")
    calls = []

    def graph_view(state, **kwargs):
        calls.append(("graph", state, kwargs))
        return {"nodes": [], "edges": [], **kwargs}

    def submit_question(state, question, mode, model_signature, *, entity_id=None):
        calls.append(("question", state, question, mode, model_signature, entity_id))
        job_id = state.enqueue(
            "local_answer", question, {"messages": []}, {"mode": mode}
        )
        return {"id": job_id, "state": state.get_job(job_id)["state"], "mode": mode}

    def question_status(state, question_id):
        job = state.get_job(question_id)
        if job is None:
            return None
        return {"id": question_id, "state": job["state"], "mode": "local"}

    graph.graph_view = graph_view
    graph.current_artifacts = current_artifacts
    query.submit_question = submit_question
    query.question_status = question_status
    monkeypatch.setitem(sys.modules, graph.__name__, graph)
    monkeypatch.setitem(sys.modules, query.__name__, query)
    server = api_module.create_server(store, TOKEN, "model-revision", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = httpx.Client(
        base_url=f"http://127.0.0.1:{server.server_address[1]}",
        headers={"Authorization": f"Bearer {TOKEN}"},
        timeout=3,
        trust_env=False,
    )
    yield client, store, calls, graph, query, server
    client.close()
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)


def test_health_is_an_unauthenticated_ready_flag_only(operator):
    client, store, *_ = operator
    store.enqueue("extract", "private", {"messages": []}, {"prompt": "secret"})
    response = client.get("/health", headers={"Authorization": ""})
    assert response.status_code == 200
    assert response.json() == {"ready": True}
    assert "Access-Control-Allow-Origin" not in response.headers
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "path", ["/v1/status", "/v1/graph", "/v1/communities", "/v1/jobs/missing"]
)
def test_every_operator_read_requires_the_separate_bearer_key(operator, path):
    client, *_ = operator
    response = client.get(path, headers={"Authorization": "Bearer wrong-key"})
    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}
    assert TOKEN not in response.text


@pytest.mark.parametrize("path", ["/health", "/v1/status", "/v1/graph"])
@pytest.mark.parametrize("origin", ["https://evil.example", "null"])
def test_browser_origins_are_rejected_before_even_health_or_auth(
    operator, path, origin
):
    client, *_ = operator
    response = client.get(path, headers={"Origin": origin})
    assert response.status_code == 403
    assert response.json() == {"error": "browser_requests_forbidden"}
    assert "Access-Control-Allow-Origin" not in response.headers


@pytest.mark.parametrize("host", ["0.0.0.0", "localhost", "example.com", "127.0.0.2"])
def test_server_cannot_bind_to_an_unapproved_host(api_module, tmp_path, host):
    with pytest.raises(ValueError, match="loopback"):
        api_module.create_server(GraphStore(tmp_path / "state"), TOKEN, "m", host=host)


@pytest.mark.parametrize("token", ["", "short", "x" * 31, "x" * 32 + "\n", "한" * 32])
def test_weak_or_header_invalid_tokens_are_rejected(api_module, tmp_path, token):
    with pytest.raises(ValueError, match="operator"):
        api_module.create_server(GraphStore(tmp_path / "state"), token, "m", port=0)


def test_operator_token_cannot_reuse_remote_inference_token(
    api_module, tmp_path, monkeypatch
):
    monkeypatch.setenv("QWEN_INFERENCE_TOKEN", TOKEN)
    with pytest.raises(ValueError, match="distinct"):
        api_module.create_server(GraphStore(tmp_path / "state"), TOKEN, "m", port=0)


def test_host_header_must_match_loopback_service(operator):
    client, *_ = operator
    response = client.get("/v1/status", headers={"Host": "evil.example"})
    assert response.status_code == 403


def test_status_returns_operational_counts_without_request_contents(operator):
    client, store, *_ = operator
    store.enqueue("extract", "private", {"messages": []}, {"prompt": "secret"})
    response = client.get("/v1/status")
    assert response.status_code == 200
    assert response.json()["jobs"]["planned"] == 1
    assert "secret" not in response.text
    assert "prompt" not in response.text


def test_graph_parameters_reach_the_bounded_graph_reader(operator):
    client, store, calls, *_ = operator
    response = client.get("/v1/graph?root=person%3Akim&depth=2&limit=17")
    assert response.status_code == 200
    assert calls == [("graph", store, {"root": "person:kim", "depth": 2, "limit": 17})]


@pytest.mark.parametrize(
    "query",
    [
        "depth=3",
        "depth=0",
        "depth=true",
        "limit=0",
        "limit=101",
        "limit=10&limit=11",
        "extra=1",
        "root=%00",
        "root=",
        "depth=1.0",
    ],
)
def test_invalid_or_ambiguous_graph_parameters_never_reach_index(operator, query):
    client, _, calls, *_ = operator
    response = client.get("/v1/graph?" + query)
    assert response.status_code == 400
    assert calls == []


def test_communities_only_include_current_revisions_at_requested_level(operator):
    client, store, *_ = operator
    for level in (0, 1):
        groups = [
            {"id": f"c{level}-{i}", "title": "정책", "level": level} for i in range(3)
        ]
        store.put_artifact(
            "community",
            str(level),
            {"group_id_version": GROUP_ID_VERSION},
            {"groups": groups, "level": level},
        )
    store.put_artifact("community", "retired", {}, {"groups": [{"id": "old"}]})
    store.invalidate_artifact("community", "retired")
    response = client.get("/v1/communities?level=1&limit=2")
    assert response.status_code == 200
    payload = response.json()
    assert [group["id"] for group in payload["communities"]] == ["c1-0", "c1-1"]
    assert payload["truncated"] is True
    assert all(
        group["version"] and group["key"] == "1" for group in payload["communities"]
    )
    assert "dependency" not in response.text


def test_question_submission_is_queued_and_repeated_question_reuses_work(operator):
    client, store, calls, *_ = operator
    body = {"question": "양육비 선지급제의 현재 단계는?", "mode": "local"}
    first = client.post("/v1/questions", json=body)
    second = client.post("/v1/questions", json=body)
    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    assert len(store.jobs()) == 1
    question_id = first.json()["id"]
    response = client.get(f"/v1/questions/{question_id}")
    assert response.status_code == 200
    assert response.json()["state"] == "planned"
    assert calls[0][4] == "model-revision"


def test_person_question_forwards_a_valid_scoped_id(operator):
    client, _, calls, *_ = operator
    response = client.post(
        "/v1/questions",
        json={"question": "김가가 발의한 법안?", "mode": "local", "entityId": "p-a"},
    )
    assert response.status_code == 202
    assert calls[0][5] == "p-a"


def test_temporary_store_contention_is_retryable_not_bad_input(operator, monkeypatch):
    """A busy factory must not make a valid question look malformed."""
    client, _, _, _, query, _ = operator

    def busy(*args, **kwargs):
        raise ValueError("pilot store busy")

    monkeypatch.setattr(query, "submit_question", busy)
    response = client.post(
        "/v1/questions", json={"question": "김가의 근거는?", "mode": "local"}
    )
    assert response.status_code == 503
    assert response.json() == {"error": "store_busy"}
    assert response.headers["Retry-After"] == "2"


@pytest.mark.parametrize(
    "body",
    [
        {"question": "김가?", "mode": "global", "entityId": "p-a"},
        {"question": "김가?", "mode": "local", "entityId": "a/b"},
        {"question": "김가?", "mode": "local", "entityId": ""},
    ],
)
def test_invalid_scoped_question_is_rejected(operator, body):
    client, _, calls, *_ = operator
    response = client.post("/v1/questions", json=body)
    assert response.status_code == 400
    assert calls == []


@pytest.mark.parametrize(
    "body",
    [
        {"question": "", "mode": "local"},
        {"question": " " * 3, "mode": "local"},
        {"question": "x" * 1001, "mode": "local"},
        {"question": "질문", "mode": "drift"},
        {"question": "질문", "mode": []},
        {"question": "질문", "mode": {}},
        {"question": "질문", "mode": "local", "token": "injected"},
        {"question": 42, "mode": "local"},
        {"question": "질문"},
        ["질문", "local"],
    ],
)
def test_invalid_question_schema_is_rejected_before_enqueuing(operator, body):
    client, store, *_ = operator
    response = client.post("/v1/questions", json=body)
    assert response.status_code == 400
    assert store.jobs() == []


@pytest.mark.parametrize(
    "body",
    [
        '{"question":"one","question":"two","mode":"local"}',
        '{"question":"q","mode":NaN}',
        '{"question":"q","mode":"local"',
    ],
)
def test_duplicate_keys_non_json_constants_and_bad_json_are_rejected(operator, body):
    client, store, *_ = operator
    response = client.post(
        "/v1/questions", content=body, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 400
    assert store.jobs() == []


def test_question_body_size_and_content_type_are_checked(operator):
    client, store, *_ = operator
    oversize = client.post(
        "/v1/questions",
        content=b"x" * 8193,
        headers={"Content-Type": "application/json"},
    )
    assert oversize.status_code == 413
    wrong_type = client.post(
        "/v1/questions", content="{}", headers={"Content-Type": "text/plain"}
    )
    assert wrong_type.status_code == 400
    assert store.jobs() == []


def test_chunked_and_duplicate_length_requests_are_rejected(operator):
    *_, server = operator
    for extra in (
        "Transfer-Encoding: chunked\r\n",
        "Content-Length: 2\r\nContent-Length: 2\r\n",
        "Content-Length: -1\r\n",
    ):
        with socket.create_connection(server.server_address, timeout=3) as connection:
            request = (
                f"POST /v1/questions HTTP/1.1\r\nHost: 127.0.0.1:{server.server_address[1]}\r\n"
                f"Authorization: Bearer {TOKEN}\r\nContent-Type: application/json\r\n{extra}\r\n"
            )
            connection.sendall(request.encode())
            response = connection.recv(4096)
            assert b" 400 " in response


def test_jobs_never_disclose_original_requests_context_or_recovery_keys(operator):
    client, store, *_ = operator
    job_id = store.enqueue(
        "extract",
        "private-key",
        {"messages": [{"content": "original prompt"}]},
        {"source": "private context"},
    )
    store.update_job(
        job_id, state="submitting", metadata={"password": "hidden", "revision": "v1"}
    )
    response = client.get(f"/v1/jobs/{job_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "submitting"
    assert payload["metadata"] == {"revision": "v1"}
    for private in (
        "original prompt",
        "private context",
        "private-key",
        "graphrag-",
        "hidden",
        "lease",
    ):
        assert private not in response.text


def test_unknown_routes_jobs_and_malformed_identifiers_do_not_leak_state(operator):
    client, *_ = operator
    for path in (
        "/admin",
        "/v1/jobs/missing",
        "/v1/questions/missing",
        "/v1/jobs/a%2Fb",
    ):
        assert client.get(path).status_code == 404
    assert client.options("/v1/status").status_code == 405
    assert client.get("/v1/status?unused=1").status_code == 400


def test_exceptions_and_oversized_results_are_replaced_with_bounded_errors(operator):
    client, _, _, graph, *_ = operator

    def oversized(*args, **kwargs):
        return {"source": "x" * (1024 * 1024 + 1)}

    graph.graph_view = oversized
    response = client.get("/v1/graph")
    assert response.status_code == 503
    assert len(response.content) < 200

    def broken(*args, **kwargs):
        raise RuntimeError("private token and raw source")

    graph.graph_view = broken
    response = client.get("/v1/graph")
    assert response.status_code == 503
    assert "private token" not in response.text


def test_raw_paths_credentials_and_questions_are_absent_from_access_logs(
    operator, caplog
):
    client, *_ = operator
    with caplog.at_level("INFO"):
        client.get(
            "/v1/jobs/private-path", headers={"Authorization": f"Bearer {TOKEN}"}
        )
    rendered = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.name.startswith("parliament_worker")
    )
    assert TOKEN not in rendered
    assert "private-path" not in rendered


def test_non_ascii_bearer_is_an_authentication_failure(operator):
    *_, server = operator
    with socket.create_connection(server.server_address, timeout=3) as connection:
        request = (
            f"GET /v1/status HTTP/1.1\r\nHost: 127.0.0.1:{server.server_address[1]}\r\n"
            "Authorization: Bearer \xff\r\n\r\n"
        )
        connection.sendall(request.encode("latin-1"))
        assert b" 401 " in connection.recv(4096)


def test_completed_question_replay_returns_200(operator):
    client, store, *_ = operator
    body = {"question": "What changed?", "mode": "global"}
    first = client.post("/v1/questions", json=body)
    job_id = first.json()["id"]
    store.update_job(job_id, state="submitting")
    store.update_job(job_id, state="completed", result={"answer": "확인 불가"})
    second = client.post("/v1/questions", json=body)
    assert second.status_code == 200
    assert second.json()["id"] == job_id


def test_secret_values_are_redacted_even_inside_result_prose(operator):
    client, store, *_ = operator
    job_id = store.enqueue("extract", "redaction", {"messages": []}, {})
    store.update_job(job_id, state="submitting")
    store.update_job(
        job_id,
        state="completed",
        result={"answer": "exfiltrate " + TOKEN, TOKEN: "key"},
    )
    response = client.get(f"/v1/jobs/{job_id}")
    assert response.status_code == 200
    assert TOKEN not in response.text
    assert "[redacted]" in response.text


def test_source_correction_hides_stale_communities_before_worker_reconcile(operator):
    client, store, *_ = operator
    store.put_source("doc", "hash-a", {})
    dependency = {
        "sources": [{"scope": "doc", "fingerprint": "hash-a", "generation": 1}]
    }
    store.put_artifact(
        "community", "old", dependency, {"groups": [{"id": "old", "level": 0}]}
    )
    store.put_source("doc", "hash-b", {})
    response = client.get("/v1/communities")
    assert response.status_code == 200
    assert response.json()["communities"] == []
