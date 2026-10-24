"""Bounded, recoverable inference transport; request intent belongs to the caller."""

import ipaddress
import json
import math
import os
import re
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

MAX_REQUEST_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_COMPLETION_BYTES = 4096
_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
_HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_ALLOWED_FIELDS = {
    "model",
    "messages",
    "max_tokens",
    "max_completion_tokens",
    "temperature",
    "top_p",
    "seed",
    "stop",
    "frequency_penalty",
    "presence_penalty",
    "user",
    "stream",
    "n",
    "response_format",
    "chat_template_kwargs",
}


class InferenceError(ValueError):
    """Expose fixed categories and recovery flags, never server text or credentials.

    Attributes:
        retryable: Whether the caller may defer and retry the same operation.
        uncertain: Whether acceptance or completion could not be established.
        status: Observed HTTP status, when a response was received.
        retry_after: Suggested deferral in seconds, capped at one hour.
    """

    def __init__(
        self,
        category: str,
        *,
        retryable: bool = False,
        uncertain: bool = False,
        status: int | None = None,
        retry_after: float = 0,
    ) -> None:
        super().__init__(category)
        self.retryable = retryable
        self.uncertain = uncertain
        self.status = status
        self.retry_after = retry_after


@dataclass(frozen=True)
class InferenceConfig:
    """An operator-configured public HTTPS endpoint and its separate inference key."""

    base_url: str
    token: str = field(repr=False)
    model: str = "local-generator"

    def __post_init__(self) -> None:
        try:
            parsed = urlsplit(self.base_url)
            host = (parsed.hostname or "").lower()
            if (
                self.base_url != self.base_url.strip()
                or any(ord(char) < 33 or char == "\\" for char in self.base_url)
                or parsed.scheme != "https"
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
                or parsed.port not in (None, 443)
                or parsed.path.rstrip("/") not in ("", "/v1")
                or "." not in host
                or host.endswith((".local", ".localhost", ".internal", ".lan", ".home"))
                or host == "localhost"
                or any(not _HOST_LABEL.fullmatch(label) for label in host.split("."))
                or not re.fullmatch(r"[\x21-\x7e]{8,512}", self.token or "")
                or self.model != "local-generator"
            ):
                raise ValueError
            try:
                ipaddress.ip_address(host)
            except ValueError:
                pass
            else:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise InferenceError("inference_configuration_invalid") from None
        object.__setattr__(self, "base_url", f"https://{host}/v1")

    @property
    def root(self) -> str:
        """Return the service root for queue paths outside the SDK's /v1 prefix."""
        return self.base_url[:-3]

    @classmethod
    def from_env(cls) -> "InferenceConfig":
        """Read only QWEN_BASE_URL and QWEN_INFERENCE_TOKEN, never the factory key."""
        return cls(
            os.environ.get("QWEN_BASE_URL", ""),
            os.environ.get("QWEN_INFERENCE_TOKEN", ""),
        )


def canonical_body(body: dict[str, Any]) -> bytes:
    """Serialize exact deterministic request bytes for persisted idempotent recovery."""
    try:
        raw = json.dumps(
            body,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (ValueError, TypeError, UnicodeError):
        raise InferenceError("inference_request_json_invalid") from None
    if not isinstance(body, dict) or len(raw) > MAX_REQUEST_BYTES:
        raise InferenceError("inference_request_size_invalid")
    return raw


def _strict_json(raw: bytes | str) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in items:
            if key in value:
                raise ValueError
            value[key] = item
        return value

    def invalid_constant(_: str) -> None:
        raise ValueError

    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)
    if not isinstance(value, dict):
        raise ValueError
    return value


def parse_completion(payload: dict[str, Any]) -> dict[str, Any]:
    """Read one finished JSON answer; reject truncation, fences and duplicate keys.

    Args:
        payload: A ChatCompletion object or a completed queue response with result.

    Returns:
        The parsed final content object, excluding any thinking output.

    Raises:
        InferenceError: If no complete, unambiguous JSON object was produced.
    """
    try:
        if not isinstance(payload, dict):
            raise ValueError
        if "result" in payload:
            if payload.get("state", "completed") != "completed":
                raise ValueError
            payload = payload["result"]
        choices = payload["choices"]
        if not isinstance(choices, list) or len(choices) != 1:
            raise ValueError
        choice = choices[0]
        if choice["finish_reason"] != "stop":
            raise ValueError
        message = choice["message"]
        content = message["content"]
        if (
            not isinstance(content, str)
            or len(content.encode("utf-8")) > MAX_COMPLETION_BYTES
            or message.get("refusal")
        ):
            raise ValueError
        return _strict_json(content)
    except (KeyError, ValueError, TypeError, AttributeError, UnicodeError):
        raise InferenceError("inference_completion_invalid") from None


def _validate_body(body: dict[str, Any], model: str) -> bytes:
    raw = canonical_body(body)
    output = body.get("max_completion_tokens", body.get("max_tokens", 1024))
    if (
        set(body) - _ALLOWED_FIELDS
        or body.get("model", model) != model
        or body.get("stream", False) is not False
        or body.get("n", 1) != 1
        or "max_tokens" in body
        and "max_completion_tokens" in body
        or type(output) is not int
        or not 1 <= output <= 1024
    ):
        raise InferenceError("inference_request_parameters_invalid")
    messages = body.get("messages")
    if not isinstance(messages, list) or not 1 <= len(messages) <= 32:
        raise InferenceError("inference_request_messages_invalid")
    for message in messages:
        if (
            not isinstance(message, dict)
            or set(message) - {"role", "content", "name"}
            or message.get("role") not in {"system", "developer", "user", "assistant"}
            or not isinstance(message.get("content"), str)
            or not message["content"]
        ):
            raise InferenceError("inference_request_messages_invalid")
    # The provider tokenizes the complete chat template before queue acceptance.
    # A UTF-8 byte ceiling rejects valid Korean evidence; the JSON size cap above
    # still bounds local work, and an over-context request is a definite HTTP 400.
    return raw


def _retry_after(value: str | None) -> float:
    try:
        seconds = float(value or "0")
    except ValueError:
        try:
            seconds = (
                parsedate_to_datetime(value or "") - datetime.now(timezone.utc)
            ).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return 0
    return min(3600, max(0, seconds)) if math.isfinite(seconds) else 0


class InferenceClient:
    """Call fixed inference paths once; the durable worker owns retry decisions."""

    def __init__(
        self,
        config: InferenceConfig,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.config = config
        self._transport = transport
        self._client = httpx.Client(
            transport=transport,
            follow_redirects=False,
            trust_env=False,
            limits=httpx.Limits(max_connections=64, max_keepalive_connections=64),
            timeout=httpx.Timeout(30, connect=10),
        )

    def _check_dns(self) -> None:
        if self._transport is not None:
            return
        host = urlsplit(self.config.root).hostname
        try:
            addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            if not addresses:
                raise OSError
            if any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
                raise InferenceError("inference_configuration_private_address")
        except OSError:
            raise InferenceError("inference_dns_unavailable", retryable=True) from None

    def _metadata(self, headers: httpx.Headers | dict[str, Any]) -> dict[str, str]:
        normalized = {
            key.lower(): value
            for key, value in headers.items()
            if isinstance(key, str) and isinstance(value, str)
        }
        metadata = {}
        for target, names in {
            "actual_model": (
                "x-model-repo",
                "x-model-id",
                "x-actual-model",
                "x-model",
                "x-backend-model",
            ),
            "revision": ("x-model-revision", "x-backend-revision", "x-revision"),
        }.items():
            for name in names:
                value = normalized.get(name)
                if value and self._safe_metadata(value):
                    metadata[target] = value
                    break
        return metadata

    def _safe_metadata(self, value: Any) -> bool:
        return (
            isinstance(value, str)
            and 1 <= len(value) <= 256
            and self.config.token not in value
            and all(32 <= ord(char) < 127 for char in value)
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        raw: bytes | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        self._check_dns()
        headers = {
            "Authorization": f"Bearer {self.config.token}",
            "Accept": "application/json",
        }
        if raw is not None:
            headers["Content-Type"] = "application/json"
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        submitted = method == "POST"
        deadline = time.monotonic() + 40
        try:
            with self._client.stream(
                method,
                self.config.root + path,
                headers=headers,
                content=raw,
                follow_redirects=False,
            ) as response:
                status = response.status_code
                retry_after = _retry_after(response.headers.get("Retry-After"))
                if 300 <= status < 400:
                    raise InferenceError("inference_redirect_rejected", status=status)
                if status not in ({200, 202} if submitted else {200}):
                    raise InferenceError(
                        "inference_http_error",
                        status=status,
                        retryable=status in {429, 503} or status >= 500,
                        uncertain=status == 504 or submitted and status in {500, 502},
                        retry_after=retry_after,
                    )
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES or time.monotonic() > deadline:
                        raise InferenceError(
                            "inference_response_limit",
                            retryable=submitted,
                            uncertain=submitted,
                            status=status,
                        )
                    chunks.append(chunk)
                try:
                    value = _strict_json(b"".join(chunks))
                except (ValueError, TypeError, UnicodeError):
                    raise InferenceError(
                        "inference_response_json_invalid",
                        retryable=submitted,
                        uncertain=submitted,
                        status=status,
                    ) from None
                # Queue envelopes carry the backend headers inside their JSON body.
                # Keep only known model fields, never credential-bearing echo headers.
                envelope_headers = value.pop("response_headers", None)
                value.pop("_modelMetadata", None)
                metadata = (
                    self._metadata(envelope_headers)
                    if isinstance(envelope_headers, dict)
                    else {}
                )
                metadata.update(self._metadata(response.headers))
                if metadata:
                    value["_modelMetadata"] = metadata
                return value
        except httpx.HTTPError:
            raise InferenceError(
                "inference_transport_unavailable",
                retryable=True,
                uncertain=True,
            ) from None

    def models(self) -> dict[str, Any]:
        """Return a whitelisted model catalog and actual model/revision metadata."""
        value = self._request("GET", "/v1/models")
        rows = value.get("data")
        if not isinstance(rows, list) or len(rows) > 64:
            raise InferenceError("inference_models_invalid")
        result: dict[str, Any] = {"object": "list", "data": []}
        for row in rows:
            if not isinstance(row, dict) or not self._safe_metadata(row.get("id")):
                raise InferenceError("inference_models_invalid")
            model = {"id": row["id"]}
            for key in ("object", "root", "owned_by"):
                if self._safe_metadata(row.get(key)):
                    model[key] = row[key]
            if type(row.get("max_model_len")) is int:
                model["max_model_len"] = row["max_model_len"]
            result["data"].append(model)
        for key in ("actual_model", "model_revision"):
            if self._safe_metadata(value.get(key)):
                result[key] = value[key]
        if value.get("_modelMetadata"):
            result["_modelMetadata"] = value["_modelMetadata"]
        return result

    def submit(self, body: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        """Submit persisted request intent once, using identical canonical bytes."""
        if not isinstance(idempotency_key, str) or not _ID.fullmatch(idempotency_key):
            raise InferenceError("inference_idempotency_key_invalid")
        raw = _validate_body(body, self.config.model)
        value = self._request(
            "POST",
            "/inference-jobs",
            raw=raw,
            idempotency_key=idempotency_key,
        )
        if (
            not isinstance(value.get("request_id"), str)
            or not _ID.fullmatch(value["request_id"])
            or value.get("state")
            not in {"received", "queued", "running", "completed", "failed"}
        ):
            raise InferenceError(
                "inference_acceptance_invalid", retryable=True, uncertain=True
            )
        return value

    def poll(self, request_id: str) -> dict[str, Any]:
        """Read an existing request; never trust a response Location as a new URL."""
        if not isinstance(request_id, str) or not _ID.fullmatch(request_id):
            raise InferenceError("inference_request_id_invalid")
        value = self._request("GET", f"/inference-jobs/{request_id}")
        if value.get("request_id", request_id) != request_id or value.get(
            "state"
        ) not in {"received", "queued", "running", "completed", "failed", "cancelled"}:
            raise InferenceError("inference_poll_invalid")
        return value

    def queue(self) -> dict[str, Any]:
        """Read server queue capacity without mutating inference jobs."""
        return self._request("GET", "/inference-queue")

    def ready(self) -> dict[str, Any]:
        """Check the active model and revision before idempotent recovery."""
        return self._request("GET", "/ready")

    def close(self) -> None:
        """Release the HTTP connection pool."""
        self._client.close()
