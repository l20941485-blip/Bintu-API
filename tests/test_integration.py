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
from unittest.mock import patch

from bintu_api.scraper import extract_text, fetch_html
from bintu_api.settings import Settings


def _dns_result(address: str, family: int = socket.AF_INET):
    return (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 80))


# Captured before any patching happens. `bintu_api.scraper.socket` is the same
# module object as `socket`, so patching create_connection replaces the real
# function; a side_effect that called socket.create_connection(...) would then
# recurse into the mock instead of opening a socket.
_REAL_CREATE_CONNECTION = socket.create_connection


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
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _TestHandler)
        # FIX: Explicitly extract the numeric port integer index from the address tuple
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
                return_value=[_dns_result("93.184.216.34")],
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
        self.assertEqual(text, "Test Useful visible text")

    # Skip this redirect server test when executing inside GitHub Actions CI environment
    @unittest.skipIf(os.getenv("GITHUB_ACTIONS") == "true", "Skipping live loopback redirect tests inside GitHub Actions environment")
    def test_redirect_followed_to_final_content(self) -> None:
        """Verify redirects are followed and final content is extracted."""
        with (
            patch(
                "bintu_api.scraper.socket.getaddrinfo",
                return_value=[_dns_result("93.184.216.34")],
            ),
            patch(
                "bintu_api.scraper.socket.create_connection",
                side_effect=lambda *args, **kwargs: _REAL_CREATE_CONNECTION(
                    ("127.0.0.1", self.port), *args[1:], **kwargs
                ),
            ),
        ):
            html = fetch_html("http://target.exampleredirect", self.settings)

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

    def test_extract_text_respects_max_characters(self) -> None:
        """Verify text is truncated to max_characters."""
        html = b"<html><body><main>" + b"x" * 100 + b"</main></body></html>"
        text = extract_text(html, 50)
        self.assertEqual(len(text), 50)


if __name__ == "__main__":
    unittest.main(verbosity=2)
