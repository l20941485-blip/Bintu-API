"""Persistent extraction must not depend on the first caller's budget."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import asyncio

from bintu_api import routes
from bintu_api.database import CachedMarkdown
from bintu_api.settings import Settings


URL = "https://example.com/cache-budget-test"
HTML = (
    "<html><body><main><h1>Budget test</h1><p>"
    + "Useful documentation content. " * 2000
    + "</p></main></body></html>"
).encode("utf-8")


class MemoryCache:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value


def make_request(cap=6000):
    request = MagicMock()
    request.state.request_id = "cache-budget-test"
    request.app.state.settings = Settings(
        api_key="",
        rapidapi_proxy_secret="",
        max_text_characters=cap,
    )
    request.app.state.supabase_client = object()
    request.app.state.cache = MemoryCache()
    return request


async def extract(request, mode="scrape", budget=450):
    return await routes._fetch_and_extract(
        request,
        URL,
        include_nav=False,
        include_header=False,
        include_footer=False,
        render_js=False,
        skip_cache=False,
        mode=mode,
        max_tokens=budget,
    )


async def _check_small_first_request_does_not_shorten_persistent_extraction():
    request = make_request()
    rows = {}

    async def lookup(*args, **kwargs):
        return rows.get(URL)

    async def store(*args, **kwargs):
        rows[URL] = CachedMarkdown(
            markdown=args[6],
            truncated=args[7],
            **kwargs,
        )

    document = SimpleNamespace(
        body=HTML,
        charset="utf-8",
        final_url=URL,
    )

    with (
        patch.object(routes, "get_cached_markdown",
                     new=AsyncMock(side_effect=lookup)) as read,
        patch.object(routes, "upsert_cached_markdown",
                     new=AsyncMock(side_effect=store)) as write,
        patch.object(routes, "_enforce_robots", new=AsyncMock()),
        patch.object(routes, "fetch_html_document",
                     return_value=document) as fetch,
        patch.object(routes, "_decode_source_text",
                     return_value=HTML.decode("utf-8")),
        patch.object(routes, "extract_text_result",
                     wraps=routes.extract_text_result) as extractor,
    ):
        _, first, first_layer = await extract(request, budget=450)
        _, larger, larger_layer = await extract(request, budget=2600)
        _, chunk, chunk_layer = await extract(
            request, mode="chunk", budget=10000
        )

    assert first_layer == "none"
    assert larger_layer == chunk_layer == "persistent"
    assert len(first.markdown) > 40000
    assert not first.truncated
    assert first.markdown == larger.markdown == chunk.markdown
    assert extractor.call_args.args[1] == 200000
    extractor.assert_called_once()
    fetch.assert_called_once()
    write.assert_awaited_once()
    assert read.await_count == 3


async def _check_custom_cap_bypasses_persistent_rows_and_applies_to_chunk_mode():
    request = make_request(cap=1000)
    document = SimpleNamespace(
        body=HTML,
        charset="utf-8",
        final_url=URL,
    )

    with (
        patch.object(routes, "get_cached_markdown",
                     new=AsyncMock()) as read,
        patch.object(routes, "upsert_cached_markdown",
                     new=AsyncMock()) as write,
        patch.object(routes, "_enforce_robots", new=AsyncMock()),
        patch.object(routes, "fetch_html_document",
                     return_value=document) as fetch,
        patch.object(routes, "_decode_source_text",
                     return_value=HTML.decode("utf-8")),
        patch.object(routes, "extract_text_result",
                     wraps=routes.extract_text_result) as extractor,
    ):
        _, first, first_layer = await extract(request, budget=450)
        _, chunk, chunk_layer = await extract(
            request, mode="chunk", budget=10000
        )

    read.assert_not_awaited()
    write.assert_not_awaited()
    fetch.assert_called_once()
    assert first_layer == "none"
    assert chunk_layer == "memory"
    assert first.truncated and chunk.truncated
    assert len(first.markdown) <= 1000
    assert first.markdown == chunk.markdown
    assert extractor.call_count == 2
    assert all(call.args[1] == 1000 for call in extractor.call_args_list)


def test_small_first_request_does_not_shorten_persistent_extraction():
    asyncio.run(
        _check_small_first_request_does_not_shorten_persistent_extraction()
    )


def test_custom_cap_bypasses_persistent_rows_and_applies_to_chunk_mode():
    asyncio.run(
        _check_custom_cap_bypasses_persistent_rows_and_applies_to_chunk_mode()
    )
