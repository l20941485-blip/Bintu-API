"""Service-level regression tests for opt-in main-content extraction."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bintu_api.extraction.cache_policy import (
    DEFAULT_MAX_TEXT_CHARACTERS,
    compute_cache_key,
)
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


def build_large_html():
    article = "<p>" + ("Meaningful article sentence. " * 500) + "</p>"
    boilerplate = (
        "<nav>Site navigation</nav>"
        "<aside>Related links</aside>"
        "<footer>Copyright and footer links</footer>"
    )
    return (
        b"<html><body>"
        + boilerplate.encode("utf-8")
        + b"<article>"
        + article.encode("utf-8")
        + b"</article>"
        + boilerplate.encode("utf-8")
        + b"</body></html>"
    )


def fake_document():
    return SimpleNamespace(
        body=build_large_html(),
        charset="utf-8",
        final_url="https://example.com/final",
    )


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
async def test_main_content_only_skips_persistent_cache():
    cache = FakeCache()
    request = make_request(cache, database_client=object())
    service = make_service(cache)

    with patch(
        "bintu_api.extraction.scrape_service.extract_main_content",
        return_value=("Cleaned article content. " * 1000, True),
    ) as extract_main_content:
        _, result, layer, _revalidated = await call_service(
            service,
            request,
            main_content_only=True,
        )


    cleaned_key = compute_cache_key(
        render_js=False,
        links="inline",
        url="https://example.com/page",
        include_nav=False,
        include_header=False,
        include_footer=False,
        main_content_only=True,
    )

    assert layer == "none"
    assert result.markdown == ("Cleaned article content. " * 1000).rstrip()
    assert result.content_cleaning == {
            "applied": True,
            "strategy": "main_content",
            "boilerplate_lines_removed": 0,
            "deduplicated_count": 0,
        }
    assert cache.data[cleaned_key] is not None
    service.persistent_cache_reader.assert_not_awaited()
    service.persistent_cache_writer.assert_not_awaited()


@pytest.mark.asyncio
async def test_main_content_only_memory_hit_skips_persistent_cache():
    document = fake_document()
    cleaned_key = compute_cache_key(
        render_js=False,
        links="inline",
        url="https://example.com/page",
        include_nav=False,
        include_header=False,
        include_footer=False,
        main_content_only=True,
    )
    cache = FakeCache({cleaned_key: document})
    request = make_request(cache, database_client=object())
    service = make_service(cache)

    with patch(
        "bintu_api.extraction.scrape_service.extract_main_content",
        return_value=("Cleaned article content. " * 1000, True),
    ):
        returned_document, result, layer, _revalidated = await call_service(
            service,
            request,
            main_content_only=True,
        )

    assert returned_document is document
    assert layer == "memory"
    assert result.content_cleaning == {
            "applied": True,
            "strategy": "main_content",
            "boilerplate_lines_removed": 0,
            "deduplicated_count": 0,
        }
    service.persistent_cache_reader.assert_not_awaited()
    service.persistent_cache_writer.assert_not_awaited()


@pytest.mark.asyncio
async def test_standard_extraction_writes_persistent_cache():
    cache = FakeCache()
    request = make_request(cache, database_client=object())
    service = make_service(cache)

    _, result, layer, _revalidated = await call_service(
        service,
        request,
        main_content_only=False,
    )

    assert layer == "none"
    assert result.markdown == "extracted"
    assert result.content_cleaning == {
            "applied": False,
            "strategy": "standard",
            "boilerplate_lines_removed": 0,
            "deduplicated_count": 0,
        }
    service.persistent_cache_reader.assert_awaited_once()
    service.persistent_cache_writer.assert_awaited_once()


@pytest.mark.asyncio
async def test_main_content_only_applies_with_links_false():
    cache = FakeCache()
    request = make_request(cache, database_client=object())
    service = make_service(cache)

    with patch(
        "bintu_api.extraction.scrape_service.extract_main_content",
        return_value=("Cleaned article content. " * 1000, True),
    ) as extract_main_content:
        _, result, _, _revalidated = await call_service(
            service,
            request,
            main_content_only=True,
            links="false",
        )

    extract_main_content.assert_called_once_with(
        fake_document().body,
        200000,
        "utf-8",
        "https://example.com/final",
        links="false",
    )
    assert result.markdown == ("Cleaned article content. " * 1000).rstrip()
    assert result.content_cleaning == {
            "applied": True,
            "strategy": "main_content",
            "boilerplate_lines_removed": 0,
            "deduplicated_count": 0,
        }
