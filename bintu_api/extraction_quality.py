from __future__ import annotations

import math
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


# ---------------------------------------------------------------------------
# Token estimation and budget enforcement
# ---------------------------------------------------------------------------


def estimate_tokens(text: str) -> int:
    """Estimate tokens using Bintu's canonical approximation: ceil(chars / 4)."""
    if not text or not text.strip():
        return 0
    return math.ceil(len(text) / 4)


def truncate_to_token_budget(text: str, max_tokens: int | None) -> tuple[str, bool]:
    """Return ``(text, truncated)`` where ``estimate_tokens(text) <= max_tokens``.

    ``max_tokens=None`` means no caller budget and returns the input unchanged.
    Truncation prefers a line boundary, then a word boundary, avoids leaving a
    dangling URL fragment, and closes a Markdown code fence it cuts through.
    """
    if max_tokens is None:
        return text, False

    if max_tokens <= 0:
        return "", bool(text)

    if estimate_tokens(text) <= max_tokens:
        return text, False

    max_chars = max_tokens * 4
    if "```" in text:
        max_chars -= 4  # Reserve room to close a fence cut by truncation.

    window = text[:max_chars]

    cut = window.rfind("\n")
    if cut < max_chars * 0.5:
        cut = max(cut, window.rfind(" "))

    if cut > 0:
        window = window[:cut]

    window = window.rstrip()
    window = re.sub(r"\((?:https?://)?[^\s)]*$", "", window).rstrip()

    if _open_fence(window):
        window = window + "\n```"

    assert estimate_tokens(window) <= max_tokens
    return window, True


def _open_fence(text: str) -> bool:
    """True when text contains an unclosed Markdown code fence."""
    return sum(1 for line in text.split("\n") if line.startswith("```")) % 2 == 1


# ---------------------------------------------------------------------------
# URL normalization and duplicate-story removal
# ---------------------------------------------------------------------------


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
        if not key.lower().startswith("utm_")
        and key.lower() not in _TRACKING_PARAMS
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

        urls = frozenset(
            normalize_url(url) for url in _URL_RE.findall(body)
        )
        body_key = (
            ""
            if urls
            else re.sub(r"\s+", " ", body).strip().casefold()
        )

        key = (title, urls, body_key)

        if title and key in seen:
            removed += 1
            continue

        seen.add(key)
        kept.extend(block)

    return "\n".join(kept), removed


# ---------------------------------------------------------------------------
# Markdown normalization
# ---------------------------------------------------------------------------


_INLINE_HEADING_RE = re.compile(
    r"(?<=[.!?)\]\u201d\"']) +(?=#{1,6} \S)"
)


def normalize_markdown(text: str) -> str:
    """Place glued Markdown headings on their own line without altering code."""
    parts = re.split(r"(```.*?(?:```|\Z))", text, flags=re.DOTALL)

    for index in range(0, len(parts), 2):
        part = _INLINE_HEADING_RE.sub("\n", parts[index])
        part = re.sub(r"[ \t]+\n", "\n", part)
        parts[index] = re.sub(r"\n{3,}", "\n\n", part)

    return "".join(parts).strip()


# ---------------------------------------------------------------------------
# Boilerplate and noise filtering
# ---------------------------------------------------------------------------


NOISE_LINE_PATTERNS = [
    re.compile(r"^list \d+ of \d+$", re.IGNORECASE),
    re.compile(r"^(?:slide|item|page) \d+ of \d+$", re.IGNORECASE),
    re.compile(r"^skip to (?:main )?content$", re.IGNORECASE),
    re.compile(r"may contain flashing|photosensitiv", re.IGNORECASE),
    re.compile(r"^محتوى رئيسي$"),
    re.compile(r"^قد يحتوي هذا الفيديو"),
]


def strip_noise_lines(text: str) -> str:
    """Remove known carousel counters, skip links, and video warnings."""
    kept = [
        line
        for line in text.split("\n")
        if not any(
            pattern.search(line.strip())
            for pattern in NOISE_LINE_PATTERNS
        )
    ]
    return "\n".join(kept)


# ---------------------------------------------------------------------------
# Sentence splitting
# ---------------------------------------------------------------------------


_DOT = "\u2024"

_PROTECT_RE = re.compile(
    r"https?://[^\s)]+"
    r"|\b(?:[A-Za-z0-9-]+\.)+(?:[A-Za-z]{2,})\b"
    r"|\b(?:[A-Z][a-z]?\.){1,3}"
    r"|\b(?:Mr|Mrs|Ms|Dr|Prof|St|vs|etc|No|Fig)\."
)


def split_sentences(text: str) -> list[str]:
    """Split sentences without breaking URLs, domains, or abbreviations."""
    protected = _PROTECT_RE.sub(
        lambda match: match.group(0).replace(".", _DOT),
        text,
    )

    parts = re.split(
        r"(?<=[.!?])\s+(?=[\"\u201c\u2018(\[]?[A-Z0-9#\u0600-\u06FF])",
        protected,
    )

    return [
        part.replace(_DOT, ".").strip()
        for part in parts
        if part.strip()
    ]
