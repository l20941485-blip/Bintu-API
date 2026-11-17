"""Contract tests for additive section-selection metadata."""

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


async def call(mode, sections):
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


@pytest.mark.asyncio
async def test_matched_sections_report_full_metadata():
    result = await call("chunk", "Background\nFeatures")

    assert result.requested_sections == ["background", "features"]
    assert result.unmatched_sections == []
    assert result.filtered is True
    assert result.section_match_status == "matched"
    assert result.warnings == []
    assert set(result.available_sections) >= {
        "Background",
        "Features",
        "Pricing",
    }


@pytest.mark.asyncio
async def test_partial_match_reports_unmatched_sections():
    result = await call("chunk", "Background\nMissing Section")

    assert result.requested_sections == ["background", "missing section"]
    assert result.unmatched_sections == ["missing section"]
    assert result.filtered is True
    assert result.section_match_status == "partial_match"
    assert result.warnings == ["No section matched: missing section."]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["scrape", "chunk", "chunked", "summarize"])
async def test_no_match_reports_no_match_metadata(mode):
    result = await call(mode, "Does Not Exist")

    assert result.requested_sections == ["does not exist"]
    assert result.unmatched_sections == ["does not exist"]
    assert result.filtered is True
    assert result.section_match_status == "no_match"
    assert result.warnings == ["No section matched: does not exist."]
    assert result.selected_sections == []
    assert result.chunks == []
    assert result.text == ""


@pytest.mark.asyncio
async def test_no_sections_reports_not_filtered():
    result = await call("chunk", None)

    assert result.requested_sections is None
    assert result.unmatched_sections is None
    assert result.available_sections is None
    assert result.filtered is False
    assert result.section_match_status == "not_filtered"
    assert result.warnings is None
