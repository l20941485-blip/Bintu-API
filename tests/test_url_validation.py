"""URL validation must reject unsafe targets before any network access."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from fastapi.testclient import TestClient

from bintu_api.scraper import TargetURLRejected
from bintu_api.settings import Settings
from main import create_app


UNSAFE_URLS = [
    "ftp://example.com/file",
    "file:///etc/passwd",
    "javascript:alert(1)",
    "data:text/html,hello",
    "https://",
    "https:///path",
    "http://127.0.0.1/",
    "http://localhost/",
    "http://[::1]/",
    "http://169.254.169.254/latest/meta-data/",
    "http://10.0.0.1/",
    "http://192.168.1.1/",
    "http://172.16.0.1/",
    "https://example.com:80@127.0.0.1/",
]


class UrlValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app(
            Settings(
                api_key="",
                rapidapi_proxy_secret="",
                render_js_enabled=False,
            )
        )
        self.client = TestClient(self.app)

    def _assert_rejected_before_fetch(self, url: str) -> None:
        with patch(
            "bintu_api.routes._enforce_robots",
            new=AsyncMock(),
        ) as robots, patch(
            "bintu_api.routes.fetch_html_document",
            side_effect=AssertionError("unsafe URL must not be fetched"),
        ) as fetch:
            response = self.client.get(
                "/api/v1/scrape/text",
                params={"url": url},
            )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(
            payload["detail"]["code"],
            "invalid_or_unsafe_url",
        )
        robots.assert_not_awaited()
        fetch.assert_not_called()

    def test_unsafe_schemes_are_rejected(self) -> None:
        for url in (
            "ftp://example.com/file",
            "file:///etc/passwd",
            "javascript:alert(1)",
            "data:text/html,hello",
        ):
            with self.subTest(url=url):
                self._assert_rejected_before_fetch(url)

    def test_missing_hosts_are_rejected(self) -> None:
        for url in (
            "https://",
            "https:///path",
        ):
            with self.subTest(url=url):
                self._assert_rejected_before_fetch(url)

    def test_loopback_targets_are_rejected(self) -> None:
        for url in (
            "http://127.0.0.1/",
            "http://localhost/",
            "http://[::1]/",
        ):
            with self.subTest(url=url):
                self._assert_rejected_before_fetch(url)

    def test_private_and_link_local_targets_are_rejected(self) -> None:
        for url in (
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.1/",
            "http://192.168.1.1/",
            "http://172.16.0.1/",
        ):
            with self.subTest(url=url):
                self._assert_rejected_before_fetch(url)

    def test_malformed_urls_are_rejected(self) -> None:
        for url in (
            "https://example.com:80@127.0.0.1/",
            "not-a-url",
            "http://",
        ):
            with self.subTest(url=url):
                self._assert_rejected_before_fetch(url)


if __name__ == "__main__":
    unittest.main(verbosity=2)