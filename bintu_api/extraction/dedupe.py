"""Duplicate-story removal for extracted Markdown.

This module owns URL normalization and duplicate-block detection so the
extraction pipeline can deduplicate repeated stories without coupling to
routing or transport.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

__all__ = ["dedupe_blocks", "normalize_url"]

_TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
    "igshid",
}

_URL_RE = re.compile(r"\((https?://[^\s)]+)\)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


def normalize_url(url: str) -> str:
    """Return a canonical URL for duplicate comparison."""
    parts = urlsplit(url.strip())

    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in _TRACKING_PARAMS
    ]

    path = parts.path.rstrip("/") or "/"
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            path,
            urlencode(query),
            "",
        )
    )


def _normalize_title(title: str) -> str:
    title = re.sub(r"[^\w\s]", " ", title.casefold())
    return re.sub(r"\s+", " ", title).strip()


def dedupe_blocks(text: str) -> tuple[str, int]:
    """Remove repeated Markdown story blocks without treating code as headings.

    A block begins at a Markdown heading outside a fenced code block. Blocks
    are duplicates when they share a normalized heading and either the same
    normalized URL set or, for blocks without URLs, the same normalized body.
    """
    lines = text.split("\n")
    blocks: list[list[str]] = [[]]
    in_fence = False

    for line in lines:
        if line.startswith("```"):
            in_fence = not in_fence
        if not in_fence and _HEADING_RE.match(line):
            blocks.append([line])
        else:
            blocks[-1].append(line)

    seen: set[tuple] = set()
    kept: list[str] = []
    removed = 0

    for index, block in enumerate(blocks):
        if index == 0:
            kept.extend(block)
            continue

        heading_match = _HEADING_RE.match(block[0])
        title = _normalize_title(heading_match.group(2)) if heading_match else ""
        body = "\n".join(block[1:])

        urls = frozenset(normalize_url(url) for url in _URL_RE.findall(body))
        body_key = "" if urls else re.sub(r"\s+", " ", body).strip().casefold()

        key = (title, urls, body_key)

        if title and key in seen:
            removed += 1
            continue

        seen.add(key)
        kept.extend(block)

    return "\n".join(kept), removed
