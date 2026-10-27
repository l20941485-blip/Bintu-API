"""Persistent extraction-cache version contract."""

import unittest
from unittest.mock import AsyncMock, MagicMock

from bintu_api.database import (
    EXTRACTOR_VERSION,
    get_cached_markdown,
    upsert_cached_markdown,
)


class CacheVersioningTests(unittest.IsolatedAsyncioTestCase):
    def make_client(self, rows):
        builder = MagicMock()
        for method in ("select", "eq", "gt", "limit", "upsert"):
            getattr(builder, method).return_value = builder
        builder.execute = AsyncMock(
            return_value=MagicMock(data=rows)
        )
        client = MagicMock()
        client.table.return_value = builder
        return client, builder

    async def test_reads_filter_by_current_extractor_version(self):
        client, builder = self.make_client([])
        result = await get_cached_markdown(
            client, "https://example.com", False, False, False, False
        )
        self.assertIsNone(result)
        builder.eq.assert_any_call(
            "extractor_version", EXTRACTOR_VERSION
        )
        builder.execute.assert_awaited_once()

    async def test_writes_explicit_current_version(self):
        client, builder = self.make_client(
            [{"url": "https://example.com"}]
        )
        await upsert_cached_markdown(
            client, "https://example.com", False, False, False, False,
            "Fresh extracted text", False,
        )
        payload = builder.upsert.call_args.args[0]
        self.assertEqual(
            payload["extractor_version"], EXTRACTOR_VERSION
        )
        self.assertNotEqual(payload["extractor_version"], "legacy")
        self.assertEqual(
            builder.upsert.call_args.kwargs["on_conflict"],
            "url,render_js,include_nav,include_header,include_footer",
        )


if __name__ == "__main__":
    unittest.main()
