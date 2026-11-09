"""Unit tests for the shared scrape-service orchestration boundary."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bintu_api.database import CachedMarkdown
from bintu_api.extraction.cache_policy import DEFAULT_MAX_TEXT_CHARACTERS, compute_cache_key
from bintu_api.extraction.request_context import ScrapeRequestContext
from bintu_api.extraction.scrape_service import ScrapeService


def fake_document(body=b"<html>fresh</html>"):
    return SimpleNamespace(body=body, charset="utf-8", final_url="https://example.com/final")


class FakeCache:
    def __init__(self, initial=None):
        self.data = dict(initial or {})

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value


def make_request(cache, database_client=None):
    settings = SimpleNamespace(max_text_characters=DEFAULT_MAX_TEXT_CHARACTERS)
    app_state = SimpleNamespace(
        settings=settings,
        supabase_client=database_client,
        cache=cache,
    )
    return SimpleNamespace(
        app=SimpleNamespace(state=app_state),
        state=SimpleNamespace(request_id="request-id"),
    )


def make_service(cache, **overrides):
    dependencies = {
        "cache": cache,
        "persistent_cache_reader": AsyncMock(return_value=None),
        "persistent_cache_writer": AsyncMock(),
        "robots_enforcer": AsyncMock(),
        "html_fetcher": MagicMock(return_value=fake_document()),
        "rendered_html_fetcher": AsyncMock(return_value=fake_document()),
        "text_extractor": MagicMock(
            return_value=SimpleNamespace(text="extracted", truncated=False)
        ),
        "source_decoder": MagicMock(return_value="source"),
        "cache_event_logger": MagicMock(),
    }
    dependencies.update(overrides)
    return ScrapeService(**dependencies)


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
    return await service.fetch_and_extract(
        context,
        "https://example.com/page",
        **arguments,
    )


@pytest.mark.asyncio
async def test_persistent_cache_hit_returns_row_without_fetching():
    cache = FakeCache()
    request = make_request(cache, database_client=object())
    cached = CachedMarkdown(
        markdown="from-persistent",
        truncated=False,
        html_tokens=10,
        tokens_saved_estimate=5,
        limiting_factor="none",
        extracted_at="2026-01-01T00:00:00+00:00",
    )
    service = make_service(
        cache,
        persistent_cache_reader=AsyncMock(return_value=cached),
    )

    document, result, layer = await call_service(service, request)

    assert document is None
    assert result is cached
    assert layer == "persistent"
    service.robots_enforcer.assert_not_awaited()
    service.html_fetcher.assert_not_called()
    service.rendered_html_fetcher.assert_not_awaited()


@pytest.mark.asyncio
async def test_memory_cache_hit_returns_document_without_fetching():
    document = fake_document()
    cache_key = compute_cache_key(
        render_js=False,
        links="inline",
        url="https://example.com/page",
    )
    cache = FakeCache({cache_key: document})
    request = make_request(cache)
    service = make_service(cache)

    returned_document, result, layer = await call_service(service, request)

    assert returned_document is document
    assert result.markdown == "extracted"
    assert layer == "memory"
    service.robots_enforcer.assert_not_awaited()
    service.html_fetcher.assert_not_called()
    service.rendered_html_fetcher.assert_not_awaited()


@pytest.mark.asyncio
async def test_fresh_fetch_enforces_robots_and_writes_memory_cache():
    cache = FakeCache()
    request = make_request(cache)
    document = fake_document()
    service = make_service(
        cache,
        html_fetcher=MagicMock(return_value=document),
    )

    returned_document, result, layer = await call_service(service, request)

    assert returned_document is document
    assert result.markdown == "extracted"
    assert layer == "none"
    service.robots_enforcer.assert_awaited_once()
    service.html_fetcher.assert_called_once()
    assert list(cache.data.values()) == [document]







