"""Credential detection for URLs and request metadata.

This module owns privacy-sensitive credential detection so REST and MCP
surfaces share one implementation without duplicating logic.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlsplit

CREDENTIAL_QUERY_PARAMS = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "auth",
        "auth_token",
        "authorization",
        "jsessionid",
        "key",
        "password",
        "phpsessid",
        "secret",
        "session",
        "sessionid",
        "sid",
        "token",
    }
)


def has_credential_params(url: str) -> bool:
    """True when the query string carries a credential-like parameter."""
    try:
        pairs = parse_qsl(urlsplit(url).query, keep_blank_values=True)
    except ValueError:
        return False
    return any(name.strip().lower() in CREDENTIAL_QUERY_PARAMS for name, _ in pairs)
