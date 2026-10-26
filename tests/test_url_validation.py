"""URL validation must reject unsafe targets before DNS or network access."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from bintu_api.scraper import TargetURLRejected, _parse_target
from bintu_api.settings import Settings
from main import create_app


class UrlValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            api_key="",
            rapidapi_proxy_secret="",
            render_js_enabled=False,
        )

    def _assert_rejected(self, url: str) -> None:
        with self.assertRaises(TargetURLRejected):
            _parse_target(url, self.settings)

    def test_requires_http_or_https(self) -> None:
        for url in (
            "ftp://example.com/file",
            "file:///etc/passwd",
            "javascript:alert(1)",
            "data:text/html,hello",
            "not-a-url",
        ):
            with self.subTest(url=url):
                self._assert_rejected(url)

    def test_requires_hostname(self) -> None:
        for url in (
            "https://",
            "https:///path",
            "http://",
        ):
            with self.subTest(url=url):
                self._assert_rejected(url)

    def test_rejects_embedded_credentials(self) -> None:
        for url in (
            "https://user@example.com/",
            "https://user:password@example.com/",
            "https://example.com:80@127.0.0.1/",
        ):
            with self.subTest(url=url):
                self._assert_rejected(url)

    def test_rejects_ambiguous_numeric_hosts(self) -> None:
        for url in (
            "http://2130706433/",
            "http://0x7f000001/",
            "http://127.1/",
            "http://::ffff:127.0.0.1/",
        ):
            with self.subTest(url=url):
                self._assert_rejected(url)

    def test_rejects_disallowed_ports(self) -> None:
        for url in (
            "http://example.com:8080/",
            "https://example.com:8443/",
            "http://example.com:0/",
        ):
            with self.subTest(url=url):
                self._assert_rejected(url)

    def test_rejects_control_characters(self) -> None:
        for url in (
            "https://example.com/\r",
            "https://example.com/\n",
            "https://example.com/\t",
        ):
            with self.subTest(url=url):
                self._assert_rejected(url)

    def test_allows_public_http_and_https(self) -> None:
        for url in (
            "http://example.com/",
            "https://example.com/page",
            "https://example.com/page?query=value",
        ):
            with self.subTest(url=url):
                parsed, host, port, path = _parse_target(url, self.settings)

                self.assertIn(host, {"example.com"})
                self.assertIn(port, {80, 443})

    def test_https_defaults_to_port_443(self) -> None:
        _, _, port, _ = _parse_target(
            "https://example.com/page",
            self.settings,
        )

        self.assertEqual(port, 443)

    def test_http_defaults_to_port_80(self) -> None:
        _, _, port, _ = _parse_target(
            "http://example.com/page",
            self.settings,
        )

        self.assertEqual(port, 80)


class UrlValidationRouteMappingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app(
            Settings(
                api_key="",
                rapidapi_proxy_secret="",
                render_js_enabled=False,
            )
        )
        self.client = TestClient(self.app)
        self.url = "http://127.0.0.1/"

    def test_route_maps_target_rejection_to_400(self) -> None:
        with patch(
            "bintu_api.routes._enforce_robots",
            new=AsyncMock(),
        ) as robots, patch(
            "bintu_api.routes.fetch_html_document",
            side_effect=TargetURLRejected(
                "The target hostname resolves to a non-public address"
            ),
        ) as fetch:
            response = self.client.get(
                "/api/v1/scrape/text",
                params={"url": self.url},
            )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(
            payload["detail"]["code"],
            "invalid_or_unsafe_url",
        )
        self.assertNotIn(self.url, response.text)

        # Robots is checked before the shared fetch boundary; the fetch then
        # raises TargetURLRejected, which the route maps to a stable 400.
        robots.assert_awaited_once()
        fetch.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)