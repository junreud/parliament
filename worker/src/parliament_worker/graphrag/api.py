"""Authenticated loopback-only GraphRAG operations; no inference keys in responses."""

import hmac
import json
import logging
import os
import re
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit

from parliament_worker.graphrag.store import GraphStore

LOGGER = logging.getLogger(__name__)
MAX_BODY_BYTES = 8192
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_REQUEST_THREADS = 16
_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
_TOKEN = re.compile(r"[\x21-\x7e]{32,512}")
_PRIVATE_FIELDS = frozenset(
    {
        "authorization",
        "apikey",
        "accesstoken",
        "token",
        "inferencetoken",
        "factorytoken",
        "password",
        "secret",
        "credentials",
        "request",
        "context",
        "idempotencykey",
        "leaseowner",
        "leaseuntil",
    }
)
_JOB_FIELDS = frozenset(
    {
        "id",
        "kind",
        "state",
        "error",
        "remote_id",
        "result",
        "metadata",
        "created_at",
        "updated_at",
    }
)


def _safe(value: Any, secrets: tuple[str, ...], depth: int = 0) -> Any:
    """Exclude transport intent and credentials from nested operator output."""
    if depth > 20:
        raise ValueError("response nesting exceeds limit")
    if isinstance(value, dict):
        return {
            _safe(str(key), secrets, depth + 1): _safe(item, secrets, depth + 1)
            for key, item in value.items()
            if re.sub(r"[^a-z0-9]", "", str(key).lower()) not in _PRIVATE_FIELDS
        }
    if isinstance(value, (list, tuple)):
        return [_safe(item, secrets, depth + 1) for item in value]
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[redacted]")
    return value


def _strict_body(raw: bytes) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result

    def invalid(_: str) -> None:
        raise ValueError("invalid JSON constant")

    body = json.loads(
        raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=invalid
    )
    if not isinstance(body, dict):
        raise ValueError("expected JSON object")
    return body


def _query(raw: str, fields: set[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in parse_qsl(raw, keep_blank_values=True, max_num_fields=8):
        if key not in fields or key in result:
            raise ValueError("invalid query fields")
        result[key] = value
    return result


def _number(
    query: dict[str, str], key: str, default: int, lower: int, upper: int
) -> int:
    raw = query.get(key, str(default))
    if not re.fullmatch(r"[0-9]{1,3}", raw):
        raise ValueError("invalid query number")
    value = int(raw)
    if not lower <= value <= upper:
        raise ValueError("query number outside bounds")
    return value


class OperatorServer(ThreadingHTTPServer):
    """Serve a bounded number of private requests while the worker continues."""

    daemon_threads = True

    def __init__(
        self, store: GraphStore, token: str, model_signature: str, host: str, port: int
    ) -> None:
        self.store = store
        self.operator_token = token
        self.model_signature = model_signature
        self.secrets = tuple(
            value
            for value in {token, os.environ.get("QWEN_INFERENCE_TOKEN", "")}
            if value
        )
        self._capacity = threading.BoundedSemaphore(MAX_REQUEST_THREADS)
        if host == "::1":
            self.address_family = socket.AF_INET6
        super().__init__((host, port), OperatorHandler)

    def process_request(self, request: socket.socket, client_address: Any) -> None:
        if not self._capacity.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._capacity.release()
            raise

    def process_request_thread(
        self, request: socket.socket, client_address: Any
    ) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._capacity.release()

    def handle_error(self, request: socket.socket, client_address: Any) -> None:
        LOGGER.warning("GraphRAG operator request failed")


class OperatorHandler(BaseHTTPRequestHandler):
    """Keep every endpoint behind a separate key and browser-origin refusal."""

    server: OperatorServer
    protocol_version = "HTTP/1.0"
    server_version = "ParliamentGraphRAG"
    sys_version = ""

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress standard request-line logs containing IDs or query text."""

    def send_error(
        self, code: int, message: str | None = None, explain: str | None = None
    ) -> None:
        self._respond(code, {"error": "invalid_request"})

    def _respond(
        self, status: int, value: Any, *, retry_after: int | None = None
    ) -> None:
        try:
            payload = json.dumps(
                _safe(value, self.server.secrets),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
            if len(payload) > MAX_RESPONSE_BYTES:
                raise ValueError("response too large")
        except (TypeError, ValueError, UnicodeError, RecursionError):
            status, payload = 503, b'{"error":"response_unavailable"}'
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if retry_after is not None:
            self.send_header("Retry-After", str(retry_after))
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        if self.command != "HEAD":
            self.wfile.write(payload)

    def _preflight(self, path: str) -> bool:
        if any(value for value in self.headers.get_all("Origin", [])):
            self._respond(403, {"error": "browser_requests_forbidden"})
            return False
        host = self.server.server_address[0]
        authority = f"[{host}]" if host == "::1" else host
        allowed_hosts = {authority, f"{authority}:{self.server.server_address[1]}"}
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1 or hosts[0] not in allowed_hosts:
            self._respond(403, {"error": "host_forbidden"})
            return False
        if path == "/health" and self.command == "GET":
            return True
        supplied = self.headers.get_all("Authorization", [])
        expected = "Bearer " + self.server.operator_token
        if len(supplied) != 1 or not hmac.compare_digest(
            supplied[0].encode("utf-8"), expected.encode("ascii")
        ):
            self._respond(401, {"error": "unauthorized"})
            return False
        return True

    def _dispatch(self) -> None:
        try:
            if len(self.path) > 2048:
                self._respond(400, {"error": "invalid_request"})
                return
            target = urlsplit(self.path)
            if (
                target.scheme
                or target.netloc
                or target.fragment
                or not target.path.startswith("/")
            ):
                raise ValueError("invalid target")
            path = unquote(target.path, errors="strict")
            if not self._preflight(path):
                return
            if self.command == "GET":
                self._get(path, target.query)
            elif self.command == "POST":
                self._post(path, target.query)
            else:
                self._respond(405, {"error": "method_not_allowed"})
        except ValueError as error:
            if str(error) == "pilot store busy":
                self._respond(503, {"error": "store_busy"}, retry_after=2)
            else:
                self._respond(400, {"error": "invalid_request"})
        except (UnicodeError, RecursionError):
            self._respond(400, {"error": "invalid_request"})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return
        except Exception:
            LOGGER.warning("GraphRAG operator operation unavailable")
            self._respond(503, {"error": "operation_unavailable"})

    do_GET = _dispatch
    do_POST = _dispatch
    do_OPTIONS = _dispatch
    do_HEAD = _dispatch
    do_PUT = _dispatch
    do_PATCH = _dispatch
    do_DELETE = _dispatch

    def _get(self, path: str, raw_query: str) -> None:
        if path == "/v1/graph":
            from parliament_worker.graphrag.index import graph_view

            query = _query(raw_query, {"root", "depth", "limit"})
            root = query.get("root")
            if root is not None and (
                not 1 <= len(root) <= 256 or any(ord(char) < 33 for char in root)
            ):
                raise ValueError("invalid graph root")
            result = graph_view(
                self.server.store,
                root=root,
                depth=_number(query, "depth", 1, 1, 2),
                limit=_number(query, "limit", 100, 1, 100),
            )
            self._respond(200, result)
            return
        if path == "/v1/communities":
            self._communities(_query(raw_query, {"level", "limit"}))
            return
        _query(raw_query, set())
        if path == "/health":
            self._respond(200, {"ready": True})
        elif path == "/v1/status":
            self._respond(200, self.server.store.status())
        elif path.startswith("/v1/jobs/"):
            job_id = path.removeprefix("/v1/jobs/")
            job = self.server.store.get_job(job_id) if _ID.fullmatch(job_id) else None
            if job is None:
                self._respond(404, {"error": "not_found"})
                return
            result = {key: value for key, value in job.items() if key in _JOB_FIELDS}
            if result.get("error") and not re.fullmatch(
                r"[a-z0-9_:-]{1,160}", str(result["error"])
            ):
                result["error"] = "job_failed"
            self._respond(200, result)
        elif path.startswith("/v1/questions/"):
            from parliament_worker.graphrag.query import question_status

            question_id = path.removeprefix("/v1/questions/")
            result = (
                question_status(self.server.store, question_id)
                if _ID.fullmatch(question_id)
                else None
            )
            (
                self._respond(200, result)
                if result is not None
                else self._respond(404, {"error": "not_found"})
            )
        else:
            self._respond(404, {"error": "not_found"})

    def _communities(self, query: dict[str, str]) -> None:
        from parliament_worker.graphrag.index import current_artifacts

        level = _number(query, "level", 0, 0, 8) if "level" in query else None
        limit = _number(query, "limit", 100, 1, 100)
        groups = []
        for artifact in current_artifacts(self.server.store, "community"):
            for group in artifact["payload"].get("groups", []):
                if (
                    level is None
                    or group.get("level", artifact["payload"].get("level")) == level
                ):
                    groups.append(
                        {
                            **group,
                            "key": artifact["key"],
                            "version": artifact["version"],
                        }
                    )
        self._respond(
            200, {"communities": groups[:limit], "truncated": len(groups) > limit}
        )

    def _post(self, path: str, raw_query: str) -> None:
        _query(raw_query, set())
        if path != "/v1/questions":
            self._respond(404, {"error": "not_found"})
            return
        lengths = self.headers.get_all("Content-Length", [])
        if (
            self.headers.get_all("Transfer-Encoding")
            or len(lengths) != 1
            or not re.fullmatch(r"[0-9]{1,8}", lengths[0])
        ):
            raise ValueError("invalid body framing")
        length = int(lengths[0])
        if length > MAX_BODY_BYTES:
            self._respond(413, {"error": "request_too_large"})
            return
        types = self.headers.get_all("Content-Type", [])
        if (
            len(types) != 1
            or types[0].split(";", 1)[0].strip().lower() != "application/json"
        ):
            raise ValueError("expected JSON content type")
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise ValueError("incomplete request body")
        body = _strict_body(raw)
        question, mode = body.get("question"), body.get("mode")
        entity_id = body.get("entityId")
        if (
            set(body) not in ({"question", "mode"}, {"question", "mode", "entityId"})
            or not isinstance(question, str)
            or not 1 <= len(question) <= 1000
            or not question.strip()
            or not isinstance(mode, str)
            or mode not in {"local", "global"}
            or (
                "entityId" in body
                and (
                    not isinstance(entity_id, str)
                    or not _ID.fullmatch(entity_id)
                    or mode != "local"
                )
            )
        ):
            raise ValueError("invalid question")
        from parliament_worker.graphrag.query import submit_question

        result = submit_question(
            self.server.store,
            question,
            mode,
            self.server.model_signature,
            **({"entity_id": entity_id} if entity_id is not None else {}),
        )
        self._respond(200 if result["state"] == "completed" else 202, result)


def create_server(
    store: GraphStore,
    token: str,
    model_signature: str,
    *,
    host: str = "127.0.0.1",
    port: int = 18790,
) -> OperatorServer:
    """Create the authenticated server without starting its request loop.

    Args:
        store: Independently locked GraphRAG state shared with the work loop.
        token: Separate operator token of at least 32 ASCII characters.
        model_signature: Current model/revision dependency for submitted questions.
        host: Only the exact IPv4 or IPv6 loopback address is accepted.
        port: Loopback TCP port; zero requests an ephemeral port for testing.
    """
    if host not in {"127.0.0.1", "::1"}:
        raise ValueError("operator API must use the exact loopback address")
    if not isinstance(token, str) or not _TOKEN.fullmatch(token):
        raise ValueError("invalid operator API token")
    inference_token = os.environ.get("QWEN_INFERENCE_TOKEN")
    if inference_token and hmac.compare_digest(
        token.encode("ascii"), inference_token.encode("utf-8")
    ):
        raise ValueError("operator and inference tokens must be distinct")
    if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
        raise ValueError("invalid operator API port")
    return OperatorServer(store, token, model_signature, host, port)


def serve(
    store: GraphStore,
    token: str,
    model_signature: str,
    *,
    host: str = "127.0.0.1",
    port: int = 18790,
) -> None:
    """Run the private API until interrupted and close all listening resources."""
    with create_server(store, token, model_signature, host=host, port=port) as server:
        server.serve_forever(poll_interval=0.25)
