"""Yield and low-yield assessment for Bintu extraction.

This module owns the low-yield detection rule (large page, almost no text,
low ratio) and the JavaScript-rendered hint logic. It is imported by the
extraction orchestrator and performs no network access.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

LOW_YIELD_MIN_HTML_TOKENS = 1000
LOW_YIELD_MAX_TEXT_TOKENS = 100
LOW_YIELD_MAX_RATIO = 0.05

_JS_MARKERS = (
    re.compile(
        r"""<div[^>]+id=["'](?:root|app|__next|__nuxt)["'][^>]*>\s*</div>""",
        re.IGNORECASE,
    ),
    re.compile(r"__NEXT_DATA__|__NUXT__|window\.__INITIAL_STATE__", re.IGNORECASE),
    re.compile(r"<noscript[^>]*>[^<]{0,200}javascript", re.IGNORECASE),
    re.compile(r"you need to enable javascript", re.IGNORECASE),
    re.compile(r"""<script[^>]*>\s*var\s+data\s*=\s*\[""", re.IGNORECASE), # inline data array (quotes.toscrape.com/js)
)

HINT_JAVASCRIPT = "This page returned little readable text because it appears to require JavaScript."
HINT_LITTLE_TEXT = "This page returned little readable text. It may require JavaScript or a login."


@dataclass(frozen=True)
class YieldAssessment:
    low_yield: bool
    reason: str | None = None
    hint: str | None = None
    ratio: float = 1.0


def assess_yield(extracted_tokens: int, html_tokens: int, html_text: str ="") -> YieldAssessment:
    ratio = (extracted_tokens / html_tokens) if html_tokens > 0 else 1.0
    low = (
        html_tokens >= LOW_YIELD_MIN_HTML_TOKENS
        and extracted_tokens <= LOW_YIELD_MAX_TEXT_TOKENS
        and ratio <= LOW_YIELD_MAX_RATIO
    )
    if not low:
        return YieldAssessment(False, None, None, round(ratio, 4))
    if html_text and any(pattern.search(html_text) for pattern in _JS_MARKERS):
        return YieldAssessment(True, "javascript_rendered", HINT_JAVASCRIPT, round(ratio, 4))
    return YieldAssessment(True, "little_text", HINT_LITTLE_TEXT, round(ratio, 4))
