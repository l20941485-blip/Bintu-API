import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from bintu_api.extraction.cleaner import suppress_boilerplate_lines
from bintu_api.scraper.fetcher import FetchedHTML
from bintu_api.scraper.robots import RobotsDecision
from bintu_api.settings import Settings
from main import create_app


def test_removes_repeated_standalone_boilerplate_labels():
    text = "\n".join(
        [
            "# Article",
            "Meaningful paragraph that should remain.",
            "Skip to main content",
            "Another meaningful paragraph.",
            "Skip to main content",
            "Final meaningful paragraph.",
            "Skip to main content",
        ]
    )

    cleaned, removed = suppress_boilerplate_lines(text)

    assert removed == 3
    assert "Skip to main content" not in cleaned
    assert "Meaningful paragraph that should remain." in cleaned
    assert "Another meaningful paragraph." in cleaned
    assert "Final meaningful paragraph." in cleaned


def test_preserves_unique_navigation_and_reference_lines():
    text = "\n".join(
        [
            "# Documentation",
            "Overview",
            "Getting started",
            "API reference",
            "1. [example.com](https://example.com)",
            "2. [docs.example.com](https://docs.example.com)",
        ]
    )

    cleaned, removed = suppress_boilerplate_lines(text)

    assert removed == 0
    assert cleaned == text


def test_preserves_headings_lists_tables_and_footnotes():
    text = "\n".join(
        [
            "# Repeated heading",
            "- Repeated item",
            "* Repeated bullet",
            "| Repeated | table |",
            "1. Repeated footnote",
            "A meaningful sentence.",
        ]
    )

    cleaned, removed = suppress_boilerplate_lines(text)

    assert removed == 0
    assert cleaned == text


def test_does_not_remove_lines_below_threshold():
    text = "\n".join(
        [
            "Skip to main content",
            "Meaningful paragraph.",
            "Skip to main content",
            "Another meaningful paragraph.",
        ]
    )

    cleaned, removed = suppress_boilerplate_lines(text)

    assert removed == 0
    assert cleaned == text



class RestBoilerplateSuppressionTests(unittest.TestCase):
    def setUp(self) -> None:
        robots_patcher = patch(
            "bintu_api.api.scrape_adapter.robots_decision",
            return_value=RobotsDecision(
                allowed=True,
                reason="disabled in tests",
                checked=False,
            ),
        )
        self.robots_patch = robots_patcher.start()
        self.addCleanup(robots_patcher.stop)

        settings = Settings(
            api_key="",
            rapidapi_proxy_secret="",
        )
        self.app = create_app(settings)
        self.client = TestClient(self.app)

    def _scrape(self, html: bytes, url: str):
        with patch(
            "bintu_api.api.scrape_adapter.fetch_html_document",
            return_value=FetchedHTML(body=html, charset=None),
        ):
            return self.client.get("/api/v1/scrape/text", params={"url": url})

    def test_rest_scrape_suppresses_repeated_boilerplate_and_caches_result(self) -> None:
        html = (
            b"<!doctype html><html><body><main>"
            b"<h1>Munich city guide</h1>"
            b"<p>Munich has useful cultural and transit information for visitors.</p>"
            b"<p>Anzeige</p>"
            b"<p>Visit the official city portal for local services.</p>"
            b"<p>Anzeige</p>"
            b"<p>The English Garden and Marienplatz are popular destinations.</p>"
            b"<p>Anzeige</p>"
            b"<p><a href=\"https://example.com/docs\">Documentation</a></p>"
            b"</main></body></html>"
        )
        url = "https://example.com/boilerplate-rest"

        fresh = self._scrape(html, url)
        self.assertEqual(fresh.status_code, 200)
        fresh_data = fresh.json()

        self.assertTrue(fresh_data["content_cleaning"]["applied"])
        self.assertEqual(
            fresh_data["content_cleaning"]["strategy"],
            "boilerplate_suppression",
        )
        self.assertGreaterEqual(
            fresh_data["content_cleaning"]["boilerplate_lines_removed"],
            3,
        )
        self.assertNotIn("Anzeige", fresh_data["text"])
        self.assertIn("Munich city guide", fresh_data["text"])
        self.assertIn("https://example.com/docs", fresh_data["text"])

        cached = self._scrape(html, url)
        self.assertEqual(cached.status_code, 200)
        cached_data = cached.json()

        self.assertTrue(cached_data["cache_hit"])
        self.assertEqual(cached_data["cache_layer"], "memory")
        self.assertEqual(cached_data["text"], fresh_data["text"])
        self.assertEqual(
            cached_data["content_cleaning"],
            fresh_data["content_cleaning"],
        )
        self.assertEqual(
            cached_data["content_quality"],
            fresh_data["content_quality"],
        )
