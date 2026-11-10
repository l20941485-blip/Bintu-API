"""Tests for section selection integration in context extraction."""

from unittest.mock import AsyncMock, patch

import pytest

from bintu_api.context import extract_context


@pytest.mark.asyncio
async def test_scrape_mode_returns_selected_sections():
    with patch(
        "bintu_api.extraction.context.rate_limit_identity",
        return_value="test-identity",
    ):
        result = await extract_context(
            request=AsyncMock(),
            url="https://example.com",
            mode="scrape",
            max_tokens=100,
            sections="Alpha",
            raw_text="# Alpha\nAlpha body\n\n# Beta\nBeta body",
            cache=False,
            persist=False,
        )

        assert result.selected_sections is not None
        assert len(result.selected_sections) == 1
        assert result.selected_sections[0]["heading"] == "Alpha"
        assert result.text == "Alpha body"
        assert result.chunks == []
        assert result.truncated is False
        assert result.limiting_factor == "none"


@pytest.mark.asyncio
async def test_scrape_mode_no_match_returns_empty_sections():
    with patch(
        "bintu_api.extraction.context.rate_limit_identity",
        return_value="test-identity",
    ):
        result = await extract_context(
            request=AsyncMock(),
            url="https://example.com",
            mode="scrape",
            max_tokens=100,
            sections="Missing",
            raw_text="# Alpha\nAlpha body",
            cache=False,
            persist=False,
        )

        assert result.selected_sections == []
        assert result.text == ""
        assert result.chunks == []
        assert result.truncated is False
        assert result.limiting_factor == "none"
        assert result.low_yield is False
        assert result.yield_hint is None


@pytest.mark.asyncio
async def test_chunk_mode_ignores_sections():
    with patch(
        "bintu_api.extraction.context.rate_limit_identity",
        return_value="test-identity",
    ):
        result = await extract_context(
            request=AsyncMock(),
            url="https://example.com",
            mode="chunk",
            max_tokens=100,
            sections="Alpha",
            raw_text="# Alpha\nAlpha body",
            cache=False,
            persist=False,
        )

        assert result.selected_sections is None


