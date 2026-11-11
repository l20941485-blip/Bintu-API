import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bintu_api.api.scrape_adapter import _fetch_and_extract
from bintu_api.scraper.fetcher import FetchedHTML
from bintu_api.settings import Settings


class PersistentCacheCredentialExclusionTests(unittest.IsolatedAsyncioTestCase):
    async def test_credential_url_is_not_read_or_written_to_persistent_cache(self) -> None:
        request = MagicMock()
        request.app.state.settings = Settings(
            api_key="",
            rapidapi_proxy_secret="",
            render_js_enabled=False,
        )
        request.app.state.supabase_client = MagicMock()
        request.app.state.cache = MagicMock()
        request.app.state.cache.get.return_value = None
        request.state.request_id = "credential-cache-test"

        document = FetchedHTML(
            final_url="https://example.com/page",
            body=b"<html><body><main><h1>Hello</h1><p>World</p></main></body></html>",
            charset="utf-8",
        )

        persistent_reader = AsyncMock(return_value=None)
        persistent_writer = AsyncMock()

        with (
            patch(
                "bintu_api.api.scrape_adapter._enforce_robots",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "bintu_api.api.scrape_adapter.fetch_html_document",
                return_value=document,
            ),
            patch(
                "bintu_api.api.scrape_adapter.get_cached_markdown",
                new=persistent_reader,
            ),
            patch(
                "bintu_api.api.scrape_adapter.upsert_cached_markdown",
                new=persistent_writer,
            ),
        ):
            await _fetch_and_extract(
                request,
                "https://example.com/page?token=secret-token",
                include_nav=False,
                include_header=False,
                include_footer=False,
                render_js=False,
                skip_cache=False,
            )

        persistent_reader.assert_not_awaited()
        persistent_writer.assert_not_awaited()