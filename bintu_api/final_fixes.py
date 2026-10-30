"""Small fixes found in the Oct 29-30 production re-tests."""

from __future__ import annotations

import re
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
    return any(
        name.strip().lower() in CREDENTIAL_QUERY_PARAMS
        for name, _ in pairs
    )


def delivered_savings(html_tokens: int, delivered_tokens: int) -> int:
    """Tokens saved for this response: source HTML estimate minus delivered text."""
    return max(0, int(html_tokens) - int(delivered_tokens))


_CLOSE_UP = re.compile(r"\s+([,.;:!?)\]])(?![\w/])")


def close_up_punctuation(line: str) -> str:
    """Close up whitespace before closing punctuation without damaging filenames or code."""
    return _CLOSE_UP.sub(r"\1", line)


def drop_empty_fences(text: str) -> str:
    """Remove fenced blocks that contain no body."""
    lines = text.split("\n")
    kept: list[str] = []
    in_fence = False
    index = 0

    while index < len(lines):
        line = lines[index]

        if not in_fence and line.startswith("```"):
            next_line = lines[index + 1] if index + 1 < len(lines) else None
            if next_line is not None and next_line.startswith("```") and next_line.strip() == "```":
                index += 2
                continue
            in_fence = True
        elif in_fence and line.startswith("```"):
            in_fence = False

        kept.append(line)
        index += 1

    return "\n".join(kept)
