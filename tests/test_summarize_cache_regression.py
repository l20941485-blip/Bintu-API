"""Regression tests for summarize mode applied to cached extractions."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from bintu_api.context import (
    CacheEconomics,
    extract_context,
)


def _request() -> SimpleNamespace:
    """Provide the minimal request surface used by extract_context."""
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(),
            ),
        ),
        state=SimpleNamespace(
            request_id="test-request",
        ),
    )


def _cache_economics() -> CacheEconomics:
    """Simulate economics persisted by an earlier scrape-mode extraction."""
    return CacheEconomics(
        html_tokens=1000,
        tokens_saved_estimate=0,
        limiting_factor="none",
        truncated=False,
        extracted_at=datetime.now(timezone.utc).isoformat(),
    )


def test_cached_summarize_reports_request_specific_truncation() -> None:
    raw_text = " ".join(
        f"Sentence {index} is deliberately long enough to consume budget."
        for index in range(20)
    )

    result = asyncio.run(
        extract_context(
            request=_request(),
            url="https://example.com/article",
            mode="summarize",
            max_tokens=20,
            cache=True,
            identity="test-identity",
            raw_text=raw_text,
            html_source_text="<html><body>Original HTML</body></html>",
            cache_hit=True,
            cache_layer="persistent",
            cache_economics=_cache_economics(),
        )
    )

    assert result.mode == "summarize"
    assert result.cache_hit is True
    assert result.truncated is True
    assert result.limiting_factor == "token_budget"
    assert result.approx_tokens <= 20
    assert result.tokens == result.approx_tokens
    assert result.chunks is not None
    assert len(result.chunks) == 1
    assert result.chunks[0]["approx_tokens"] == result.approx_tokens


def test_cached_summarize_within_budget_is_not_truncated() -> None:
    raw_text = "Short cached article text."

    result = asyncio.run(
        extract_context(
            request=_request(),
            url="https://example.com/article",
            mode="summarize",
            max_tokens=100,
            cache=True,
            identity="test-identity",
            raw_text=raw_text,
            html_source_text="<html><body>Original HTML</body></html>",
            cache_hit=True,
            cache_layer="persistent",
            cache_economics=_cache_economics(),
        )
    )

    assert result.mode == "summarize"
    assert result.cache_hit is True
    assert result.truncated is False
    assert result.limiting_factor == "none"
    assert result.approx_tokens <= 100
    assert result.text == raw_text