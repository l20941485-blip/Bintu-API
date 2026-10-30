"""low_yield detection: a large page that produced almost no text.

Seen live: https://quotes.toscrape.com/js/ returned 23 tokens from 1,452 HTML tokens with
truncated=false and limiting_factor="none", so an agent had no way to know the page was
rendered by JavaScript.

Rule (all three must hold, tune the constants against your own fixtures):
    html_tokens      >= LOW_YIELD_MIN_HTML_TOKENS   the page is not tiny (example.com is 145)
    extracted_tokens <= LOW_YIELD_MAX_TEXT_TOKENS   almost nothing came out
    ratio            <= LOW_YIELD_MAX_RATIO         ... relative to the markup

Large pages with real content are not flagged because they exceed the text threshold
(BBC Africa: 1,582 of 93,200; IANA: 554 of 2,737).

Integration (bintu_api/context.py, inside extract_context after raw_text is normalized):

    from bintu_api.yield_check import assess_yield
    assessment = assess_yield(count_tokens(raw_text), html_tokens, html_source_text)
    ...
    return ContextResult(..., low_yield=assessment.low_yield, yield_hint=assessment.hint)

ContextResult gets two new fields:    low_yield: bool = False,  yield_hint: str | None = None
The MCP envelope (mcp.py, and the streamable route that builds the same dict) adds:

    "low_yield": context.low_yield,
    **({"yield_hint": context.yield_hint} if context.low_yield else {}),

`html_source_text` is empty on a persistent-cache hit (the HTML is not stored), so the
JavaScript-marker reason is only available on fresh fetches; the numeric rule still works.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

LOW_YIELD_MIN_HTML_TOKENS = 1000
LOW_YIELD_MAX_TEXT_TOKENS = 100
LOW_YIELD_MAX_RATIO = 0.05

_JS_MARKERS = (
    re.compile(r"""<div[^>]+id=["'](?:root|app|__next|__nuxt)["'][^>]*>\s*</div>""", re.IGNORECASE),
    re.compile(r"__NEXT_DATA__|__NUXT__|window\.__INITIAL_STATE__", re.IGNORECASE),
    re.compile(r"<noscript[^>]*>[^<]{0,200}javascript", re.IGNORECASE),
    re.compile(r"you need to enable javascript", re.IGNORECASE),
    re.compile(r"""<script[^>]*>\s*var\s+data\s*=\s*\[""", re.IGNORECASE),  # inline data array (quotes.toscrape.com/js)
)

HINT_JAVASCRIPT = (
    "This page returned little readable text because it appears to require JavaScript."
)
HINT_LITTLE_TEXT = (
    "This page returned little readable text. It may require JavaScript or a login."
)


@dataclass(frozen=True)
class YieldAssessment:
    low_yield: bool
    reason: str | None = None
    hint: str | None = None
    ratio: float = 1.0


def assess_yield(extracted_tokens: int, html_tokens: int, html_text: str = "") -> YieldAssessment:
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
