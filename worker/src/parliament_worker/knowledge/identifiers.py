"""Identifier validation mirrors the public backend's explicit source namespaces."""

import re
from typing import Any

NAMESPACE_PATTERN = re.compile(r"[A-Z0-9_]{1,64}")


def validate_identifiers(identifiers: Any) -> None:
    """Reject identifiers that cannot cross the Java import boundary.

    Args:
        identifiers: At most 20 explicit namespace/value pairs from a manifest
            or operator-reviewed entity. Values remain case sensitive.

    Raises:
        ValueError: A namespace or value violates the fixed backend contract.
    """
    if not isinstance(identifiers, list) or len(identifiers) > 20:
        raise ValueError("invalid identifiers")
    for identifier in identifiers:
        if not isinstance(identifier, dict):
            raise ValueError("invalid identifier")
        namespace = identifier.get("namespace")
        if not isinstance(namespace, str) or not NAMESPACE_PATTERN.fullmatch(namespace):
            raise ValueError("invalid identifier namespace")
        value = identifier.get("value")
        if not isinstance(value, str) or not value.strip() or "\x00" in value:
            raise ValueError("invalid identifier value")
        try:
            length = len(value.encode("utf-16-le")) // 2
        except UnicodeEncodeError as error:
            raise ValueError("invalid identifier value") from error
        if length > 255:
            raise ValueError("invalid identifier value")
