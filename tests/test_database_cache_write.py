"""Persistent cache write verification."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from bintu_api.database import CacheWriteFailed, upsert_cached_markdown


class CacheWriteTests(unittest.IsolatedAsyncioTestCase):
    def _client(self, rows):
        response = MagicMock()
        response.data = rows
        table = MagicMock()
        table.upsert.return_value.execute = AsyncMock(return_value=response)
        client = MagicMock()
        client.table.return_value = table
        return client, table

    async def test_successful_upsert_returns_one_row(self) -> None:
        client, table = self._client([{"url": "https://example.com"}])

        await upsert_cached_markdown(
            client,
            "https://example.com",
            False,
            False,
            False,
            False,
            "Example",
            False,
        )

        table.upsert.assert_called_once()
        table.upsert.return_value.execute.assert_awaited_once()

    async def test_empty_response_raises_cache_write_failed(self) -> None:
        client, _ = self._client([])

        with self.assertRaises(CacheWriteFailed):
            await upsert_cached_markdown(
                client,
                "https://example.com",
                False,
                False,
                False,
                False,
                "Example",
                False,
            )

    async def test_empty_markdown_is_not_cached(self) -> None:
        client, table = self._client([{"url": "https://example.com"}])

        with self.assertRaises(ValueError):
            await upsert_cached_markdown(
                client,
                "https://example.com",
                False,
                False,
                False,
                False,
                "   ",
                False,
            )

        table.upsert.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)