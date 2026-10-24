"""Build bounded remote requests shared by graph and community prompts."""

from typing import Any

from parliament_worker.graphrag.inputs import canonical
from parliament_worker.graphrag.output_contract import enforce_output_contract
from parliament_worker.graphrag.system_prompt import SYSTEM


def request(
    task: str,
    data: dict[str, Any],
    *,
    output_tokens: int = 768,
    provider_tokenization: bool = False,
) -> dict[str, Any]:
    """Build a request; let the provider tokenize oversized leaf evidence exactly."""
    body = enforce_output_contract(
        {
            "model": "local-generator",
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": canonical({"task": task, **data}).decode()},
            ],
            "max_completion_tokens": output_tokens,
            "stream": False,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "chat_template_kwargs": {"enable_thinking": False},
        }
    )
    request_bytes = sum(
        len(message["content"].encode()) for message in body["messages"]
    )
    if not provider_tokenization and request_bytes + output_tokens + 256 > 4096:
        raise ValueError("GraphRAG prompt exceeds conservative context allowance")
    return body
