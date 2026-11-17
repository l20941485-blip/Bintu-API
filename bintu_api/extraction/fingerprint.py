"""Cosmetic-independent fingerprints for extracted content."""

from __future__ import annotations

import hashlib
import re
import unicodedata

_WHITESPACE = re.compile(r"\s+")
_PUNCTUATION = re.compile(r"[\W_]+", re.UNICODE)


def normalize_content(text: str) -> str:
    """Normalize cosmetic extraction differences while preserving wording."""
    if not text:
        return ""

    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.casefold()
    normalized = _PUNCTUATION.sub(" ", normalized)
    normalized = _WHITESPACE.sub(" ", normalized)
    return normalized.strip()


def compute_content_fingerprint(text: str) -> str:
    """Return a stable SHA-256 fingerprint for normalized extracted content."""
    normalized = normalize_content(text)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
