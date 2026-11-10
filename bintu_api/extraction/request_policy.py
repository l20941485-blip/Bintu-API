"""Validate scrape request options and select a fetch strategy.

This module contains pure request-policy decisions. It does not fetch
documents, enforce robots rules, access caches, query databases, or extract
text.
"""

from __future__ import annotations

from typing import Literal

LINK_MODES = ("inline", "footnotes", "false")


def validate_link_mode(links: str) -> None:
    """Validate the requested link mode."""
    if links not in LINK_MODES:
        raise ValueError("links must be one of: inline, footnotes, false")


def resolve_fetch_strategy(render_js: bool) -> Literal["rendered", "threaded"]:
    """Return the fetch strategy implied by the JavaScript-rendering flag."""
    return "rendered" if render_js else "threaded"
