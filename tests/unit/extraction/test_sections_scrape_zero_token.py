from unittest.mock import AsyncMock, patch

import pytest

from bintu_api.extraction.context import extract_context


@pytest.mark.asyncio
async def test_scrape_sections_matches_bold_list_item_label():
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
                "# Guides\n\n"
                "- **Overview of HTTP**\n"
                "  The basic features of HTTP.\n\n"
                "- **MIME types**\n"
                "  Since HTTP/1.0, different types of content can be "
                "transmitted. This article explains how this is accomplished "
                "using the Content-Type header and the MIME standard.\n\n"
                "- **Compression in HTTP**\n"
                "  Browsers and servers compress their messages.\n"
            ),
            cache=False,
            persist=False,
        )

    assert result.selected_sections is not None
    assert result.selected_sections
    assert result.selected_sections[0]["heading"] == "MIME types"
    assert result.tokens > 0
    assert "Content-Type header" in result.text
