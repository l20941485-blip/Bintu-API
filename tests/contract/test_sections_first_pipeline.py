"""Contract tests: sections must filter before scrape, chunk, and summarize."""

from unittest.mock import AsyncMock, patch

import pytest

from bintu_api.extraction.context import extract_context


MARKDOWN = """# Background

Background body.

# Features

Features body.

# Pricing

Pricing body.
"""


async def call(mode: str, sections):
    with patch(
        "bintu_api.extraction.context.rate_limit_identity",
        return_value="test-identity",
    ):
        return await extract_context(
            request=AsyncMock(),
            url="https://example.com",
            mode=mode,
            max_tokens=100,
            sections=sections,
            raw_text=MARKDOWN,
            cache=False,
            persist=False,
        )


def chunk_text(result):
    return "\n".join(chunk["text"] for chunk in (result.chunks or []))


@pytest.mark.asyncio
async def test_scrape_returns_selected_sections_in_document_order():
    result = await call("scrape", "Features\nBackground")

    assert "Background body." in result.text
    assert "Features body." in result.text
    assert "Pricing body." not in result.text
    assert result.text.index("Background body.") < result.text.index(
        "Features body."
    )
    assert [section["heading"] for section in result.selected_sections] == [
        "Background",
        "Features",
    ]


@pytest.mark.asyncio
async def test_chunk_splits_only_selected_sections():
    result = await call("chunk", "Background\nFeatures")

    joined = chunk_text(result)

    assert "Background body." in joined
    assert "Features body." in joined
    assert "Pricing body." not in joined
    assert [section["heading"] for section in result.selected_sections] == [
        "Background",
        "Features",
    ]


@pytest.mark.asyncio
async def test_chunked_alias_splits_only_selected_sections():
    result = await call("chunked", "Background\nFeatures")

    joined = chunk_text(result)

    assert "Background body." in joined
    assert "Features body." in joined
    assert "Pricing body." not in joined


@pytest.mark.asyncio
async def test_summarize_uses_only_selected_sections():
    result = await call("summarize", "Features")

    assert "Features body." in result.text
    assert "Background body." not in result.text
    assert "Pricing body." not in result.text
    assert [section["heading"] for section in result.selected_sections] == [
        "Features"
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["scrape", "chunk", "chunked", "summarize"])
async def test_no_matching_sections_returns_no_page_content(mode):
    result = await call(mode, "Does Not Exist")

    assert result.text == ""
    assert result.chunks == []
    assert result.chunk_count == 0
    assert result.selected_sections == []
    assert "Background body." not in result.text
    assert "Features body." not in result.text
    assert "Pricing body." not in result.text


@pytest.mark.asyncio
async def test_no_sections_preserves_full_page_chunk_behavior():
    result = await call("chunk", None)

    joined = chunk_text(result)

    assert "Background body." in joined
    assert "Features body." in joined
    assert "Pricing body." in joined
    assert result.selected_sections is None
