"""Persistent extraction-cache version contract."""

import hashlib
import unittest
from unittest.mock import AsyncMock, MagicMock

from bintu_api.extraction.cache_store import EXTRACTOR_VERSION, get_cached_markdown, upsert_cached_markdown


class CacheVersioningTests(unittest.IsolatedAsyncioTestCase):
    def make_client(self, rows):
        builder = MagicMock()
        for method in ("select", "eq", "gt", "limit", "upsert"):
            getattr(builder, method).return_value = builder
        builder.execute = AsyncMock(return_value=MagicMock(data=rows))
        client = MagicMock()
        client.table.return_value = builder
        return client, builder

    async def test_reads_filter_by_current_extractor_version(self):
        client, builder = self.make_client([])
        result = await get_cached_markdown(client, "https://example.com", False, False, False, False)
        self.assertIsNone(result)
        builder.eq.assert_any_call("extractor_version", EXTRACTOR_VERSION)
        builder.execute.assert_awaited_once()

    async def test_writes_explicit_current_version(self):
        client, builder = self.make_client([{"url": "https://example.com"}])
        await upsert_cached_markdown(
            client,
            "https://example.com",
            False,
            False,
            False,
            False,
            "Fresh extracted text",
            False,
        )
        payload = builder.upsert.call_args.args[0]
        self.assertEqual(payload["extractor_version"], EXTRACTOR_VERSION)
        self.assertNotEqual(payload["extractor_version"], "legacy")
        self.assertEqual(
            builder.upsert.call_args.kwargs["on_conflict"],
            "url,render_js,include_nav,include_header,include_footer",
        )


    async def test_reads_content_hash(self):
        content_hash = hashlib.sha256(b"Cached body").hexdigest()
        client, _ = self.make_client(
            [
                {
                    "markdown": "Cached body",
                    "truncated": False,
                    "html_tokens": 0,
                    "tokens_saved_estimate": 0,
                    "limiting_factor": "none",
                    "extracted_at": "2026-10-25T00:00:00+00:00",
                    "content_hash": content_hash,
                }
            ]
        )

        result = await get_cached_markdown(
            client,
            "https://example.com",
            False,
            False,
            False,
            False,
        )

        self.assertEqual(result.content_hash, content_hash)

    async def test_missing_content_hash_returns_empty_string(self):
        client, _ = self.make_client(
            [
                {
                    "markdown": "Cached body",
                    "truncated": False,
                    "html_tokens": 0,
                    "tokens_saved_estimate": 0,
                    "limiting_factor": "none",
                    "extracted_at": "2026-10-25T00:00:00+00:00",
                }
            ]
        )

        result = await get_cached_markdown(
            client,
            "https://example.com",
            False,
            False,
            False,
            False,
        )

        self.assertEqual(result.content_hash, "")

    async def test_invalid_content_hash_returns_empty_string(self):
        client, _ = self.make_client(
            [
                {
                    "markdown": "Cached body",
                    "truncated": False,
                    "html_tokens": 0,
                    "tokens_saved_estimate": 0,
                    "limiting_factor": "none",
                    "extracted_at": "2026-10-25T00:00:00+00:00",
                    "content_hash": 123,
                }
            ]
        )

        result = await get_cached_markdown(
            client,
            "https://example.com",
            False,
            False,
            False,
            False,
        )

        self.assertEqual(result.content_hash, "")


if __name__ == "__main__":
    unittest.main()


