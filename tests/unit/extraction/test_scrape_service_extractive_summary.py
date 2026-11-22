from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bintu_api.extraction.cache_policy import DEFAULT_MAX_TEXT_CHARACTERS
from bintu_api.extraction.request_context import ScrapeRequestContext
from bintu_api.extraction.scrape_options import ScrapeOptions
from bintu_api.extraction.scrape_service import ScrapeService


class FakeCache:
    def __init__(self, initial=None):
        self.data = dict(initial or {})
        self.get_calls = 0

    def get(self, key):
        self.get_calls += 1
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value


def fake_document():
    return SimpleNamespace(
        body=b"<html><body><p>Document body.</p></body></html>",
        charset="utf-8",
        final_url="https://example.com/final",
    )


def make_request(cache):
    settings = SimpleNamespace(max_text_characters=DEFAULT_MAX_TEXT_CHARACTERS)
    app_state = SimpleNamespace(
        settings=settings,
        supabase_client=object(),
        cache=cache,
    )
    return SimpleNamespace(
        app=SimpleNamespace(state=app_state),
        state=SimpleNamespace(request_id="request-id"),
    )


def make_service(cache):
    return ScrapeService(
        cache=cache,
        persistent_cache_reader=AsyncMock(return_value=None),
        persistent_cache_writer=AsyncMock(),
        robots_enforcer=AsyncMock(),
        html_fetcher=MagicMock(return_value=fake_document()),
        rendered_html_fetcher=AsyncMock(return_value=fake_document()),
        text_extractor=MagicMock(
            return_value=SimpleNamespace(text="extracted", truncated=False)
        ),
        source_decoder=MagicMock(return_value="source"),
        cache_event_logger=MagicMock(),
    )


async def call_service(service, request, **overrides):
    arguments = {
        "include_nav": False,
        "include_header": False,
        "include_footer": False,
        "render_js": False,
    }
    arguments.update(overrides)

    context = ScrapeRequestContext(
        settings=request.app.state.settings,
        database_client=request.app.state.supabase_client,
        request_id=request.state.request_id,
    )
    options = ScrapeOptions(**arguments)

    return await service.fetch_and_extract(
        context,
        "https://example.com/page",
        options,
    )


@pytest.mark.asyncio
async def test_summary_is_omitted_by_default():
    cache = FakeCache()
    request = make_request(cache)
    service = make_service(cache)

    with patch(
        "bintu_api.extraction.scrape_service.extract_main_content",
        return_value=(
            (
                "# Guide\n\n"
                "Bintu extracts clean Markdown for retrieval.\n\n"
                "It preserves headings and source context.\n\n"
                "## Usage\n\n"
                "Call the extraction endpoint with a public URL."
            ),
            True,
        ),
    ):
        _, result, _, _ = await call_service(
            service,
            request,
            main_content_only=True,
        )

    assert "extractive_summary" not in result.content_cleaning


@pytest.mark.asyncio
async def test_leading_summary_is_added_to_content_cleaning():
    cache = FakeCache()
    request = make_request(cache)
    service = make_service(cache)
    markdown = (
        "# Guide\n\n"
        "Bintu extracts clean Markdown for retrieval.\n\n"
        "It preserves headings and source context.\n\n"
        "## Usage\n\n"
        "Call the extraction endpoint with a public URL."
    )

    with patch(
        "bintu_api.extraction.scrape_service.extract_main_content",
        return_value=(markdown, True),
    ):
        _, result, _, _ = await call_service(
            service,
            request,
            main_content_only=True,
            summary_mode="leading",
            summary_sentence_count=2,
        )

    summary = result.content_cleaning["extractive_summary"]

    assert summary["applied"] is True
    assert summary["mode"] == "leading"
    assert summary["requested_sentence_count"] == 2
    assert summary["returned_sentence_count"] == 2
    assert summary["truncated"] is False
    assert len(summary["sentences"]) == 2

    first = summary["sentences"][0]
    assert first["text"] == "Bintu extracts clean Markdown for retrieval."
    assert first["heading_path"] == ["Guide"]
    assert markdown[first["char_start"]:first["char_end"]] == first["text"]


@pytest.mark.asyncio
async def test_key_sentences_are_returned_in_source_order():
    cache = FakeCache()
    request = make_request(cache)
    service = make_service(cache)
    markdown = (
        "# Guide\n\n"
        "Bintu extracts clean Markdown for retrieval.\n\n"
        "It preserves headings and source context.\n\n"
        "## Usage\n\n"
        "Call the extraction endpoint with a public URL."
    )

    with patch(
        "bintu_api.extraction.scrape_service.extract_main_content",
        return_value=(markdown, True),
    ):
        _, result, _, _ = await call_service(
            service,
            request,
            main_content_only=True,
            summary_mode="key_sentences",
            summary_sentence_count=2,
        )

    summary = result.content_cleaning["extractive_summary"]
    offsets = [
        sentence["char_start"]
        for sentence in summary["sentences"]
    ]

    assert summary["applied"] is True
    assert summary["mode"] == "key_sentences"
    assert offsets == sorted(offsets)
    assert all(
        markdown[sentence["char_start"]:sentence["char_end"]]
        == sentence["text"]
        for sentence in summary["sentences"]
    )
