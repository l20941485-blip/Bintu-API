"""Regression tests for filtering sections before chunking."""

from unittest.mock import AsyncMock, patch

import pytest

from bintu_api.extraction.context import extract_context


async def extract(markdown, sections, max_tokens=100):
    with patch(
        "bintu_api.extraction.context.rate_limit_identity",
        return_value="test-identity",
    ):
        return await extract_context(
            request=AsyncMock(),
            url="https://example.com",
            mode="chunk",
            max_tokens=max_tokens,
            sections=sections,
            raw_text=markdown,
            cache=False,
            persist=False,
        )


@pytest.mark.asyncio
async def test_chunk_mode_applies_sections_before_chunking():
    result = await extract(
        "# Background\nBackground content.\n\n"
        "# Features\nFeatures content.\n\n"
        "# Pricing\nPricing content.",
        ["Background", "Features"],
    )

    joined = "\n".join(chunk["text"] for chunk in (result.chunks or []))

    assert "Background content." in joined
    assert "Features content." in joined
    assert "Pricing content." not in joined
    assert [section["heading"] for section in result.selected_sections] == [
        "Background",
        "Features",
    ]
    assert result.chunk_count == len(result.chunks)


@pytest.mark.asyncio
async def test_chunk_mode_no_matching_sections_returns_empty():
    result = await extract(
        "# Background\nBackground content.\n\n"
        "# Features\nFeatures content.",
        ["NonExistentSection"],
    )

    assert result.text == ""
    assert result.chunks == []
    assert result.chunk_count == 0
    assert result.selected_sections == []


@pytest.mark.asyncio
async def test_chunk_mode_preserves_entire_selected_section_across_chunks():
    body = "\n\n".join(
        f"Selected paragraph {index}: " + "selected content. " * 15
        for index in range(12)
    )
    result = await extract(
        f"# Background\n{body}\n\n"
        "# Pricing\nExcluded pricing content.",
        ["Background"],
        max_tokens=100,
    )

    joined = "\n".join(chunk["text"] for chunk in (result.chunks or []))

    assert "Selected paragraph 0:" in joined
    assert "Selected paragraph 11:" in joined
    assert "Excluded pricing content." not in joined
    assert len(result.chunks) > 1
    assert all(chunk["approx_tokens"] <= 100 for chunk in result.chunks)
