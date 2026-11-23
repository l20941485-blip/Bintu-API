"""Persistent-cache reads and writes must degrade safely on failure."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bintu_api.extraction.persistent_cache import (
    read_persistent_cache,
    write_persistent_cache,
)


class PersistentCacheResilienceTests(unittest.IsolatedAsyncioTestCase):
    def _result(self):
        return SimpleNamespace(
            markdown="cached markdown",
            truncated=False,
            html_tokens=0,
            tokens_saved_estimate=0,
            limiting_factor="none",
            extracted_at="2026-01-01T00:00:00+00:00",
            page_title="Example",
            content_fingerprint="fingerprint",
            content_cleaning={},
        )

    async def test_read_failure_returns_none(self):
        reader = AsyncMock(side_effect=RuntimeError("database unavailable"))

        result = await read_persistent_cache(
            object(),
            "https://example.com",
            False,
            False,
            False,
            False,
            reader,
            request_id="req-read-failure",
        )

        self.assertIsNone(result)
        reader.assert_awaited_once()

    async def test_read_timeout_returns_none(self):
        async def slow_reader(*args, **kwargs):
            await asyncio.sleep(0.05)

        result = await read_persistent_cache(
            object(),
            "https://example.com",
            False,
            False,
            False,
            False,
            slow_reader,
            request_id="req-read-timeout",
            timeout_seconds=0.01,
        )

        self.assertIsNone(result)

    async def test_write_failure_does_not_raise(self):
        writer = AsyncMock(side_effect=RuntimeError("database unavailable"))

        await write_persistent_cache(
            object(),
            "https://example.com",
            False,
            False,
            False,
            False,
            self._result(),
            writer,
            request_id="req-write-failure",
        )

        writer.assert_awaited_once()

    async def test_write_timeout_does_not_raise(self):
        async def slow_writer(*args, **kwargs):
            await asyncio.sleep(0.05)

        await write_persistent_cache(
            object(),
            "https://example.com",
            False,
            False,
            False,
            False,
            self._result(),
            slow_writer,
            request_id="req-write-timeout",
            timeout_seconds=0.01,
        )

    async def test_successful_write_is_attempted(self):
        writer = AsyncMock(return_value=None)

        await write_persistent_cache(
            object(),
            "https://example.com",
            False,
            False,
            False,
            False,
            self._result(),
            writer,
            request_id="req-write-success",
        )

        writer.assert_awaited_once()


    async def test_read_failure_logs_safe_error_details(self):
        reader = AsyncMock(
            side_effect=RuntimeError("supabase error: permission denied")
        )

        with self.assertLogs("bintu_api.scrape", level="WARNING") as captured:
            result = await read_persistent_cache(
                object(),
                "https://example.com",
                False,
                False,
                False,
                False,
                reader,
                request_id="req-read-diagnostic",
            )

        self.assertIsNone(result)
        self.assertTrue(
            any(
                "supabase_cache_lookup_failed" in message
                and "RuntimeError" in message
                and "permission denied" in message
                for message in captured.output
            )
        )

    async def test_write_failure_logs_safe_error_details(self):
        writer = AsyncMock(
            side_effect=RuntimeError("supabase error: permission denied")
        )

        with self.assertLogs("bintu_api.scrape", level="WARNING") as captured:
            await write_persistent_cache(
                object(),
                "https://example.com",
                False,
                False,
                False,
                False,
                self._result(),
                writer,
                request_id="req-write-diagnostic",
            )

        self.assertTrue(
            any(
                "supabase_cache_upsert_failed" in message
                and "RuntimeError" in message
                and "permission denied" in message
                for message in captured.output
            )
        )


if __name__ == "__main__":
    unittest.main()
