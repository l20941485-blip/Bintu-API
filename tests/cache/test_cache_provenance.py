"""Persistent-cache preservation of page title and content fingerprint."""

import unittest
from unittest.mock import AsyncMock, MagicMock

from bintu_api.extraction.cache_store import (
    CachedMarkdown,
    get_cached_markdown,
    upsert_cached_markdown,
)
from bintu_api.extraction.persistent_cache import write_persistent_cache

URL = "https://example.com/article"
TITLE = "Example Page"
FINGERPRINT = "sha256:" + "1" * 64


class CacheProvenanceTests(unittest.IsolatedAsyncioTestCase):
    def make_client(self, rows):
        builder = MagicMock()
        for method in ("select", "eq", "gt", "limit", "upsert"):
            getattr(builder, method).return_value = builder
        builder.execute = AsyncMock(return_value=MagicMock(data=rows))
        client = MagicMock()
        client.table.return_value = builder
        return client, builder

    async def test_writer_persists_title_and_fingerprint(self):
        client, builder = self.make_client([{"url": URL}])

        await upsert_cached_markdown(
            client,
            URL,
            False,
            False,
            False,
            False,
            "Cached body",
            False,
            page_title=TITLE,
            content_fingerprint=FINGERPRINT,
        )

        payload = builder.upsert.call_args.args[0]
        self.assertEqual(payload["page_title"], TITLE)
        self.assertEqual(payload["content_fingerprint"], FINGERPRINT)

    async def test_reader_selects_and_restores_title_and_fingerprint(self):
        client, builder = self.make_client(
            [{
                "markdown": "Cached body",
                "truncated": False,
                "page_title": TITLE,
                "content_fingerprint": FINGERPRINT,
            }]
        )

        result = await get_cached_markdown(
            client, URL, False, False, False, False
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.page_title, TITLE)
        self.assertEqual(result.content_fingerprint, FINGERPRINT)

        selected = {
            column.strip()
            for column in builder.select.call_args.args[0].split(",")
        }
        self.assertIn("page_title", selected)
        self.assertIn("content_fingerprint", selected)

    async def test_reader_handles_missing_null_and_invalid_metadata(self):
        for metadata in (
            {},
            {"page_title": None, "content_fingerprint": None},
            {"page_title": 123, "content_fingerprint": []},
        ):
            with self.subTest(metadata=metadata):
                client, _ = self.make_client(
                    [{
                        "markdown": "Cached body",
                        "truncated": False,
                        **metadata,
                    }]
                )

                result = await get_cached_markdown(
                    client, URL, False, False, False, False
                )

                self.assertIsNotNone(result)
                self.assertIsNone(result.page_title)
                self.assertIsNone(result.content_fingerprint)

    async def test_helper_forwards_title_and_fingerprint(self):
        writer = AsyncMock()
        result = CachedMarkdown(
            markdown="Cached body",
            truncated=False,
            page_title=TITLE,
            content_fingerprint=FINGERPRINT,
        )

        await write_persistent_cache(
            MagicMock(),
            URL,
            False,
            False,
            False,
            False,
            result,
            writer,
        )

        writer.assert_awaited_once()
        kwargs = writer.await_args.kwargs
        self.assertEqual(kwargs["page_title"], TITLE)
        self.assertEqual(kwargs["content_fingerprint"], FINGERPRINT)
