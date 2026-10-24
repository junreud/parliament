"""Public-link shape checks; live verification remains separate evidence."""

import ipaddress
from urllib.parse import urlparse


def public_https(value: str) -> bool:
    """Reject local, credential-bearing and non-HTTPS destinations."""
    try:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme != "https" or not host or parsed.username or parsed.password:
            return False
        if host == "localhost" or host.endswith(
            (".localhost", ".local", ".internal", ".test", ".invalid")
        ):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return "." in host and " " not in host
    except ValueError:
        return False
