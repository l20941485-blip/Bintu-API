from unittest.mock import AsyncMock, patch

import pytest

from bintu_api.extraction.context import extract_context


@pytest.mark.asyncio
async def test_scrape_sections_matches_plain_label_with_link():
    with patch(
        "bintu_api.extraction.context.rate_limit_identity",
        return_value="test-identity",
    ):
        result = await extract_context(
            request=AsyncMock(),
            url="https://example.com",
            mode="scrape",
            max_tokens=8000,
            sections="MIME types",
            raw_text=(
                "HTTP basics\n"
                "HTTP is an application-layer protocol.\n\n"
                "MIME types (https://example.com/mime-types)\n"
                "Since HTTP/1.0, different types of content can be "
                "transmitted. This article explains how this is accomplished "
                "using the Content-Type header and the MIME standard.\n\n"
                "Compression in HTTP\n"
                "Browsers and servers compress their messages.\n"
            ),
            cache=False,
            persist=False,
        )

    assert result.selected_sections is not None
    assert result.selected_sections
    assert result.selected_sections[0]["heading"] == "MIME types"
    assert result.tokens > 0
    assert "Content-Type header" in result.text
    assert "Compression in HTTP" not in result.text


@pytest.mark.asyncio
async def test_scrape_sections_does_not_match_sentence_containing_selector():
    with patch(
        "bintu_api.extraction.context.rate_limit_identity",
        return_value="test-identity",
    ):
        result = await extract_context(
            request=AsyncMock(),
            url="https://example.com",
            mode="scrape",
            max_tokens=8000,
            sections="MIME types",
            raw_text=(
                "MIME types are important for web development.\n\n"
                "Compression in HTTP\n"
                "Browsers and servers compress their messages.\n"
            ),
            cache=False,
            persist=False,
        )

    assert result.selected_sections == []
    assert result.text == ""
    assert result.tokens == 0
