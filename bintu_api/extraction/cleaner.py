"""Shared markdown/text cleanup and documentation-noise removal.

This module owns small, pure text transformations used by both the scraper
and extraction-quality layers. It never performs network access or owns
business policy.
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit

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

NOISE_LINE_PATTERNS = [
    re.compile(r"^list \d+ of \d+$", re.IGNORECASE),
    re.compile(r"^(?:slide|item|page) \d+ of \d+$", re.IGNORECASE),
    re.compile(r"^skip to (?:main )?content$", re.IGNORECASE),
    re.compile(r"may contain flashing|photosensitiv", re.IGNORECASE),
    re.compile(r"^\u0627\u0644\u0645\u062d\u062a\u0648\u0649 \u0627\u0644\u0631\u0626\u064a\u0633\u064a$"),
    re.compile(r"^\u0642\u062f \u064a\u062d\u062a\u0648\u064a \u0647\u0630\u0627 \u0627\u0644\u0641\u064a\u062f\u064a\u0648"),
]


def strip_noise_lines(text: str) -> str:
    """Remove known carousel counters, skip links, and video warnings."""
    kept = [
        line for line in text.split("\n") if not any(pattern.search(line.strip()) for pattern in NOISE_LINE_PATTERNS)
    ]
    return "\n".join(kept)

_INLINE_HEADING_RE = re.compile(r"(?<=[.!?)\]\u201d\"']) +(?=#{1,6} \S)")


def normalize_markdown(text: str) -> str:
    """Place glued Markdown headings on their own line without altering code."""
    parts = re.split(r"(```.*?(?:```|\Z))", text, flags=re.DOTALL)

    for index in range(0, len(parts), 2):
        part = _INLINE_HEADING_RE.sub("\n", parts[index])
        part = re.sub(r"[ \t]+\n", "\n", part)
        parts[index] = re.sub(r"\n{3,}", "\n\n", part)

    return "".join(parts).strip()

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

    return [part.replace(_DOT, ".").strip() for part in parts if part.strip()]

PERMALINK_SELECTOR = ", ".join(
    [
        "a.headerlink",  # Sphinx, MkDocs
        "a.header-anchor",  # VuePress / VitePress
        "a.anchor",  # GitHub-style
        "a.anchorjs-link",
        "a.hash-link",  # Docusaurus
        "a.permalink",
        "a.heading-anchor",
        "a.direct-link",
        "a[class*='permalink']",
        "a[class*='headerlink']",
        "a[aria-label='Permalink']",
        "a[title*='ermalink']",
        "a[title*='Link to this']",
    ]
)

_PERMALINK_GLYPHS = {
    "\u00b6",
    "#",
    "\u00a7",
    "\U0001f517",
    "\u00a4",
}  # pilcrow, hash, section, link emoji
_HEADINGISH = ["h1", "h2", "h3", "h4", "h5", "h6", "dt", "caption", "summary"]

_ZERO_WIDTH = "\u200b\u200c\u200d\u2060\ufeff"


def _is_permalink_text(text: str) -> bool:
    text = text.strip(_ZERO_WIDTH + " \t\r\n")
    if not text:
        return True
    if text in _PERMALINK_GLYPHS:
        return True
    return len(text) == 1 and unicodedata.category(text) == "Co"


def strip_permalinks(soup) -> int:
    """Remove permalink anchors. Returns how many were removed.

    Class-based rules cover the common doc generators; the generic rule removes
    an anchor whose whole text is a permalink glyph, points inside the page, and
    sits in a heading / definition term / caption.
    """
    removed = 0
    for anchor in soup.select(PERMALINK_SELECTOR):
        if anchor.find_parent(["pre", "code"]):
            continue
        label = anchor.get_text(strip=True)
        if not _is_permalink_text(label):
            anchor.unwrap()
        else:
            anchor.decompose()
        removed += 1
    for anchor in soup.find_all("a", href=True):
        if (
            anchor.find_parent(["pre", "code"]) is None
            and _is_permalink_text(anchor.get_text())
            and anchor["href"].strip().startswith("#")
            and anchor.find_parent(_HEADINGISH) is not None
        ):
            anchor.decompose()
            removed += 1
    return removed


def _norm(text: str) -> str:
    text = re.sub(r"[\u00b6#\u00a7]", " ", text.casefold())
    return re.sub(r"\s+", " ", text).strip()


def should_drop_title(title: str, first_heading: str) -> bool:
    """Suppress an exact title duplicate or a delimiter-separated site wrapper."""
    t, h = _norm(title), _norm(first_heading)
    if not t or not h:
        return False
    if t == h:
        return True
    if len(h) < 8:
        return False
    delimiter = r"(?:\s+[\u2014\u2013-]\s+|\s*\|\s*)"
    return bool(re.fullmatch(re.escape(h) + delimiter + r".+", t) or re.fullmatch(r".+" + delimiter + re.escape(h), t))


def same_document(base_url: str | None, resolved) -> bool:
    """True when a resolved link points at the page being read (any fragment)."""
    if not base_url:
        return False
    base = urlsplit(base_url)

    def key(parts):
        return (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path or "/",
            parts.query,
        )

    return key(base) == key(resolved)
