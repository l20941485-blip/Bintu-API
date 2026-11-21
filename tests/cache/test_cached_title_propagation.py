"""Preserve page titles through persistent-cache context transformation."""

import unittest
from unittest.mock import MagicMock

from bintu_api.extraction.cache import build_cache_economics
from bintu_api.extraction.cache_store import CachedMarkdown
from bintu_api.extraction.context import extract_context

TITLE = "Example Page"
TIMESTAMP = "2026-11-18T12:25:31.036811+00:00"


class CachedTitlePropagationTests(unittest.IsolatedAsyncioTestCase):
    def make_economics(self, title, title_source="html_title"):
        cached = CachedMarkdown(
            markdown="# Heading\n\nA useful paragraph.",
            truncated=False,
            html_tokens=100,
            extracted_at=TIMESTAMP,
            page_title=title,
            page_title_source=title_source if title else "none",
        )
        return build_cache_economics(None, cached, "persistent")

    async def test_cache_economics_carries_title(self):
        economics = self.make_economics(TITLE)
        self.assertIsNotNone(economics)
        self.assertEqual(economics.page_title, TITLE)
        self.assertEqual(economics.page_title_source, "html_title")

    async def test_persistent_hit_preserves_result_and_chunk_titles(self):
        for strategy in ("sequential", "semantic"):
            with self.subTest(strategy=strategy):
                result = await extract_context(
                    MagicMock(),
                    url="https://example.com/article",
                    mode="chunk",
                    max_tokens=100,
                    identity="test-identity",
                    settings=MagicMock(),
                    raw_text="# Heading\n\nA useful paragraph.",
                    cache_hit=True,
                    cache_layer="persistent",
                    document=None,
                    cache_economics=self.make_economics(TITLE),
                    chunk_strategy=strategy,
                )

                self.assertEqual(result.page_title, TITLE)
                self.assertEqual(result.extracted_at, TIMESTAMP)
                self.assertTrue(result.chunks)
                self.assertEqual(result.page_title_source, "html_title")
                chunk_ids = [chunk["chunk_id"] for chunk in result.chunks]
                chunk_hashes = [
                    chunk["chunk_sha256"] for chunk in result.chunks
                ]

                self.assertEqual(len(chunk_ids), len(set(chunk_ids)))
                self.assertEqual(len(chunk_hashes), len(set(chunk_hashes)))

                for chunk in result.chunks:
                    self.assertEqual(chunk["page_title"], TITLE)
                    self.assertEqual(
                        chunk["page_title_source"],
                        "html_title",
                    )
                    self.assertTrue(chunk["chunk_id"].startswith("sha256:"))
                    self.assertEqual(
                        len(chunk["chunk_sha256"]),
                        64,
                    )

    async def test_legacy_cached_title_can_remain_null(self):
        result = await extract_context(
            MagicMock(),
            url="https://example.com/article",
            mode="chunk",
            max_tokens=100,
            identity="test-identity",
            settings=MagicMock(),
            raw_text="# Heading\n\nA useful paragraph.",
            cache_hit=True,
            cache_layer="persistent",
            document=None,
            cache_economics=self.make_economics(None),
        )

        self.assertIsNone(result.page_title)
        self.assertEqual(result.page_title_source, "none")
        self.assertTrue(result.chunks)
        for chunk in result.chunks:
            self.assertIsNone(chunk["page_title"])
            self.assertEqual(chunk["page_title_source"], "none")
