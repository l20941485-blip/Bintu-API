from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from bintu_api.extraction.context import count_tokens, extract_context
from bintu_api.settings import Settings


def _dummy_request() -> MagicMock:
    request = MagicMock()
    request.headers = {}
    request.state.request_id = "test-request-id"
    request.app.state.settings = Settings(
        api_key="",
        rapidapi_proxy_secret="",
        render_js_enabled=False,
    )
    request.app.state.cache = MagicMock()
    request.app.state.cache.get.return_value = None
    return request


@pytest.mark.asyncio
async def test_chunk_mode_approx_tokens_matches_joined_final_text() -> None:
    markdown = (
        "# Section One\n\n"
        + ("Alpha sentence for chunking. " * 25)
        + "\n\n# Section Two\n\n"
        + ("Beta sentence for chunking. " * 25)
    )

    result = await extract_context(
        _dummy_request(),
        url="https://example.com/article",
        raw_text=markdown,
        mode="chunk",
        max_tokens=80,
    )

    assert result.chunk_count > 1
    expected_final_text = "\n\n---\n\n".join(chunk["text"] for chunk in result.chunks)
    assert result.text == expected_final_text
    assert result.approx_tokens == count_tokens(result.text)
    assert result.approx_tokens > sum(chunk["tokens"] for chunk in result.chunks)


@pytest.mark.asyncio
async def test_chunk_mode_empty_selection_sets_zero_approx_tokens() -> None:
    markdown = "# Background\nBackground content.\n\n# Features\nFeatures content."

    result = await extract_context(
        _dummy_request(),
        url="https://example.com/article",
        raw_text=markdown,
        mode="chunk",
        sections=["NonExistentSection"],
    )

    assert result.chunks == []
    assert result.chunk_count == 0
    assert result.text == ""
    assert result.approx_tokens == 0
