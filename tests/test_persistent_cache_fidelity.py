"""Persistent-cache hits must preserve extracted Markdown exactly."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from bintu_api.database import CachedMarkdown
from bintu_api.settings import Settings
from main import create_app


CACHED_MARKDOWN = (
    "# Example Domain\n"
    "This domain is for use in examples.\n"
    "\n"
    "| Column A | Column B |\n"
    "| --- | --- |\n"
    "| 1 | 2 |"
)


def _cached_row() -> CachedMarkdown:
    return CachedMarkdown(
        markdown=CACHED_MARKDOWN,
        truncated=False,
        html_tokens=100,
        tokens_saved_estimate=50,
        limiting_factor="none",
        extracted_at="2026-01-01T00:00:00Z",
    )


class PersistentCacheFidelityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app(
            Settings(
                api_key="",
                rapidapi_proxy_secret="",
                render_js_enabled=False,
            )
        )

        # The persistent-cache path is only enabled when the application has
        # a database client. Use a harmless sentinel; the database functions
        # are patched below and should never be called for real.
        self.app.state.supabase_client = object()
        self.client = TestClient(self.app)

    def test_persistent_cache_hit_preserves_newlines(self) -> None:
        with patch(
            "bintu_api.routes.get_cached_markdown",
            new=AsyncMock(return_value=_cached_row()),
        ):
            response = self.client.get(
                "/api/v1/scrape/text",
                params={"url": "https://example.com/page"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertEqual(payload["cache_layer"], "persistent")
        self.assertEqual(payload["text"], CACHED_MARKDOWN)
        self.assertIn("\n", payload["text"])
        self.assertIn("| Column A | Column B |", payload["text"])

    def test_persistent_cache_hit_does_not_reextract_markdown(self) -> None:
        with patch(
            "bintu_api.routes.get_cached_markdown",
            new=AsyncMock(return_value=_cached_row()),
        ), patch(
            "bintu_api.routes.extract_text_result"
        ) as extract:
            response = self.client.get(
                "/api/v1/scrape/text",
                params={"url": "https://example.com/page"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["cache_layer"], "persistent")
        extract.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)