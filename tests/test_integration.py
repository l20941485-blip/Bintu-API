"""Integration tests using a real local HTTP server.

These tests verify the full fetch -> parse -> extract pipeline
with actual HTTP responses, while still respecting SSRF protection
by mocking DNS resolution and connection targeting.
"""

import os
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from bintu_api.scraper import extract_text, extract_text_result, fetch_html
from bintu_api.settings import Settings


def _dns_result(address: str, family: int = socket.AF_INET, port: int = 80):
    return (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port))


# Captured before any patching happens. `bintu_api.scraper.socket` is the same
# module object as `socket`, so patching create_connection replaces the real
# function; a side_effect that called socket.create_connection(...) would then
# recurse into the mock instead of opening a socket.
_REAL_CREATE_CONNECTION = socket.create_connection
_REAL_GETADDRINFO = socket.getaddrinfo


def _resolve_test_dns(host: str, port: int, *args, **kwargs):
    if host == "target.example":
        return [_dns_result("93.184.216.34", port=port)]
    return _REAL_GETADDRINFO(host, port, *args, **kwargs)


class _TestHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler that serves HTML content."""

    def do_GET(self) -> None:
        if self.path == "/":
            body = (
                b"<html><head><title>Test</title></head>"
                b"<body><header>Header noise</header>"
                b"<main>Useful <b>visible</b> text</main>"
                b"<footer>Footer noise</footer>"
                b"<nav>Navigation noise</nav>"
                b"<script>script noise</script>"
                b"<style>.hidden { display: none; }</style>"
                b"</body></html>"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass  # Suppress request logs during tests


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Bind to localhost
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _TestHandler)
        # FIX: Extract only the port number integer (index 1) from the address tuple
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        self.settings = Settings(api_key="", rapidapi_proxy_secret="")

    # Skip this network server test when executing inside GitHub Actions CI environment
    @unittest.skipIf(os.getenv("GITHUB_ACTIONS") == "true", "Skipping live loopback server tests inside GitHub Actions environment")
    def test_full_pipeline_fetches_and_extracts_text(self) -> None:
        """Verify the complete flow: HTTP fetch -> HTML parse -> text extraction."""
        with (
            patch(
                "bintu_api.scraper.socket.getaddrinfo",
                side_effect=_resolve_test_dns,
            ),
            patch(
                "bintu_api.scraper.socket.create_connection",
                side_effect=lambda *args, **kwargs: _REAL_CREATE_CONNECTION(
                    ("127.0.0.1", self.port), *args[1:], **kwargs
                ),
            ),
        ):
            html = fetch_html("http://target.example", self.settings)

        self.assertIn(b"Useful", html)
        text = extract_text(html, 6000)
        self.assertEqual(text, "# Test\nUseful visible text")

    # Skip this redirect server test when executing inside GitHub Actions CI environment
    @unittest.skipIf(os.getenv("GITHUB_ACTIONS") == "true", "Skipping live loopback redirect tests inside GitHub Actions environment")
    def test_redirect_followed_to_final_content(self) -> None:
        """Verify redirects are followed and final content is extracted."""
        with (
            patch(
                "bintu_api.scraper.socket.getaddrinfo",
                side_effect=_resolve_test_dns,
            ),
            patch(
                "bintu_api.scraper.socket.create_connection",
                side_effect=lambda *args, **kwargs: _REAL_CREATE_CONNECTION(
                    ("127.0.0.1", self.port), *args[1:], **kwargs
                ),
            ),
        ):
            html = fetch_html("http://target.example/redirect", self.settings)

        self.assertIn(b"Useful", html)

    def test_extract_text_with_include_options(self) -> None:
        """Verify include_nav/include_header/include_footer options work."""
        html = (
            b"<html><body>"
            b"<header>Header content</header>"
            b"<main>Main content</main>"
            b"<footer>Footer content</footer>"
            b"<nav>Nav content</nav>"
            b"</body></html>"
        )

        # Default: removes header, footer, nav
        text_default = extract_text(html, 6000)
        self.assertEqual(text_default, "Main content")

        # Include nav
        text_with_nav = extract_text(html, 6000, include_nav=True)
        self.assertIn("Nav content", text_with_nav)
        self.assertNotIn("Header content", text_with_nav)

        # Include header
        text_with_header = extract_text(html, 6000, include_header=True)
        self.assertIn("Header content", text_with_header)
        self.assertNotIn("Nav content", text_with_header)

        # Include footer
        text_with_footer = extract_text(html, 6000, include_footer=True)
        self.assertIn("Footer content", text_with_footer)
        self.assertNotIn("Header content", text_with_footer)

        # Include all
        text_all = extract_text(
            html, 6000, include_nav=True, include_header=True, include_footer=True
        )
        self.assertIn("Header content", text_all)
        self.assertIn("Main content", text_all)
        self.assertIn("Footer content", text_all)
        self.assertIn("Nav content", text_all)

    def test_extract_text_preserves_block_boundaries(self) -> None:
        html = (
            b"<h1>Page title</h1>"
            b"<p>First <strong>paragraph</strong>!</p>"
            b"<p>Second paragraph<br>continued here.</p>"
            b"<ul><li>First item</li><li>Second item</li></ul>"
        )

        text = extract_text(html, 6000)

        self.assertEqual(
            text,
            "# Page title\nFirst paragraph!\nSecond paragraph\ncontinued here."
            "\nFirst item\nSecond item",
        )

    def test_extract_text_deduplicates_matching_document_title(self) -> None:
        html = (
            b"<html><head><title>Page title</title></head>"
            b"<body><h1>Page title</h1><p>Content.</p></body></html>"
        )

        text = extract_text(html, 6000)

        self.assertEqual(text, "# Page title\nContent.")

    def test_extract_text_formats_heading_levels(self) -> None:
        html = b"<h1>Main title</h1><h2>Section</h2><h3>Subsection</h3>"

        text = extract_text(html, 6000)

        self.assertEqual(text, "# Main title\n## Section\n### Subsection")

    def test_extract_text_prefers_article_over_surrounding_page_content(self) -> None:
        html = (
            b"<html><body><main><aside>Sidebar noise</aside>"
            b"<article><h1>Article heading</h1><p>Article content.</p></article>"
            b"<aside>Related links</aside></main></body></html>"
        )

        text = extract_text(html, 6000)

        self.assertEqual(text, "# Article heading\nArticle content.")

    def test_extract_text_uses_main_when_article_is_missing(self) -> None:
        html = (
            b"<html><body><aside>Outside sidebar</aside>"
            b"<main><h1>Main heading</h1><p>Main content.</p></main>"
            b"<aside>More sidebar</aside></body></html>"
        )

        text = extract_text(html, 6000)

        self.assertEqual(text, "# Main heading\nMain content.")

    def test_extract_text_falls_back_to_document_when_no_main_content(self) -> None:
        html = b"<html><body><h1>Fallback heading</h1><p>Fallback content.</p></body></html>"

        text = extract_text(html, 6000)

        self.assertEqual(text, "# Fallback heading\nFallback content.")

    def test_extract_text_removes_hidden_and_common_boilerplate(self) -> None:
        html = (
            b"<article><h1>Story</h1><p>Useful article text.</p>"
            b"<div class='share-tools'><button>Share</button></div>"
            b"<div class='related-content'>Related story</div>"
            b"<div hidden>Hidden text</div><div style='display: none'>Invisible</div>"
            b"<custom-element>Text in attribute-less element</custom-element>"
            b"</article>"
        )

        text = extract_text(html, 6000)

        self.assertEqual(
            text,
            "# Story\nUseful article text.\nText in attribute-less element",
        )

    def test_extract_text_preserves_links_as_absolute_destinations(self) -> None:
        html = b"<main><p>Read <a href='/guide/start?lang=en'>the guide</a>.</p></main>"

        extracted = extract_text_result(
            html,
            6000,
            base_url="https://example.com/redirected/page",
        )

        self.assertEqual(
            extracted.text,
            "Read the guide (https://example.com/guide/start?lang=en).",
        )
        self.assertFalse(extracted.truncated)

    def test_extract_text_marks_truncation_and_ends_at_word_boundary(self) -> None:
        extracted = extract_text_result(b"<p>one two three four</p>", 10)

        self.assertEqual(extracted.text, "one two")
        self.assertTrue(extracted.truncated)

    def test_extract_text_uses_declared_charset_for_unicode(self) -> None:
        html = '<meta charset="utf-8"><p>إختبار — café</p>'.encode("utf-8")

        text = extract_text(html, 6000)

        self.assertEqual(text, "إختبار — café")

    def test_extract_text_cleans_invisible_word_separators(self) -> None:
        html = (
            "<meta charset='utf-8'><main><p>kept \u200bin the cockpit</p></main>"
        ).encode("utf-8")

        text = extract_text(html, 6000)

        self.assertEqual(text, "kept in the cockpit")

    def test_extract_text_formats_table_rows(self) -> None:
        html = (
            b"<table><thead><tr><th>Domain</th><th>Language</th></tr></thead>"
            b"<tbody><tr><td>xn--kgbechtv</td><td>Arabic</td></tr>"
            b"<tr><td>xn--hgbk6aj7f53bba</td><td>Persian</td></tr></tbody></table>"
        )

        text = extract_text(html, 6000)

        self.assertEqual(
            text,
            "Domain | Language\n--- | ---\nxn--kgbechtv | Arabic\nxn--hgbk6aj7f53bba | Persian",
        )

    def test_extract_text_prefers_common_div_main_container(self) -> None:
        html = (
            b"<html><body><nav>Site navigation</nav>"
            b"<div id='main'><h1>HTML Tables</h1><p>Example data</p>"
            b"<table><tr><th>Company</th><th>Country</th></tr>"
            b"<tr><td>Acme</td><td>Gambia</td></tr></table></div>"
            b"</body></html>"
        )

        text = extract_text(html, 6000)

        self.assertEqual(
            text,
            "# HTML Tables\nExample data\nCompany | Country\n--- | ---\nAcme | Gambia",
        )

    def test_quality_fixtures_match_golden_output(self) -> None:
        fixture_dir = Path(__file__).parent / "fixtures" / "extraction_quality"
        for html_path in sorted(fixture_dir.glob("*.html")):
            with self.subTest(fixture=html_path.name):
                expected_path = html_path.with_suffix(".txt")
                expected = expected_path.read_text(encoding="utf-8").rstrip("\n")
                actual = extract_text(html_path.read_bytes(), 6000)
                self.assertEqual(actual, expected)

    def test_extract_text_respects_max_characters(self) -> None:
        """Verify text is truncated to max_characters."""
        html = b"<html><body><main>" + b"x" * 100 + b"</main></body></html>"
        text = extract_text(html, 50)
        # FIX: Removed the double len() call bug
        self.assertEqual(len(text), 50)


if __name__ == "__main__":
    unittest.main(verbosity=2)
