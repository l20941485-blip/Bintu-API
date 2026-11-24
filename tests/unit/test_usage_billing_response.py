"""Verify usage billing fields are present in the scrape response envelope."""

import unittest
from datetime import UTC, datetime
from types import SimpleNamespace

from bintu_api.extraction.cache_store import CachedMarkdown
from bintu_api.extraction.output import build_scrape_response


class UsageBillingResponseTests(unittest.TestCase):
    def setUp(self):
        self.markdown = "# Title\n\nExtracted content for testing."
        self.result = CachedMarkdown(
            markdown=self.markdown,
            truncated=False,
            html_tokens=500,
            tokens_saved_estimate=400,
            limiting_factor="none",
            extracted_at=datetime.now(UTC).isoformat(),
            content_hash="abc123",
        )
        self.settings = SimpleNamespace(service_version="test", cache_ttl_seconds=300)
        self.request_id = "req-test-123"

    def test_fresh_fetch_shows_no_cache_credit(self):
        """Fresh fetches must report cache_credit_applied=False and full billable units."""
        response = build_scrape_response(
            url="https://example.com/doc",
            result=self.result,
            document=SimpleNamespace(
                body=b"<html>...</html>",
                final_url="https://example.com/doc",
                status=200,
                redirect_count=0,
                content_type="text/html",
            ),
            cache_layer="none",  # Fresh fetch
            request_id=self.request_id,
            settings=self.settings,
            mode="scrape",
        )

        self.assertIsNotNone(response.usage)
        self.assertFalse(response.usage["cache_credit_applied"])
        self.assertEqual(response.usage["unit"], "context_tokens")
        # Billable units should match approx_tokens for fresh fetch
        self.assertGreater(response.usage["billable_units"], 0)

    def test_cache_hit_shows_cache_credit(self):
        """Cache hits must report cache_credit_applied=True."""
        response = build_scrape_response(
            url="https://example.com/doc",
            result=self.result,
            document=None,  # No document on cache hit
            cache_layer="persistent",  # Cache hit
            request_id=self.request_id,
            settings=self.settings,
            mode="scrape",
        )

        self.assertIsNotNone(response.usage)
        self.assertTrue(response.usage["cache_credit_applied"])
        self.assertEqual(response.usage["unit"], "context_tokens")
        # Note: classify_usage returns the original token count but flags the credit.
        # The middleware later zeros out the DB record, but the response shows the potential cost saved.
        # If your policy is to show 0 billable units in the response too, adjust classify_usage or this assertion.
        # Currently, we just verify the flag is true.

    def test_chunk_mode_uses_chunk_tokens_unit(self):
        """Chunk mode requests must report unit='chunk_tokens'."""
        response = build_scrape_response(
            url="https://example.com/doc",
            result=self.result,
            document=None,
            cache_layer="memory",
            request_id=self.request_id,
            settings=self.settings,
            mode="chunk",
        )

        self.assertIsNotNone(response.usage)
        self.assertEqual(response.usage["unit"], "chunk_tokens")


if __name__ == "__main__":
    unittest.main()
