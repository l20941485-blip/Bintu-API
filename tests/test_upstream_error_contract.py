"""Upstream failures must be stable, actionable, and privacy-safe."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from bintu_api.scraper import UpstreamHTTPError
from bintu_api.settings import Settings
from main import create_app


class UpstreamErrorContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.url = "https://example.com/private?token=secret-value"
        self.app = create_app(
            Settings(
                api_key="",
                rapidapi_proxy_secret="",
                render_js_enabled=False,
            )
        )
        self.client = TestClient(self.app)

    def _scrape(self):
        return self.client.get(
            "/api/v1/scrape/text",
            params={"url": self.url},
        )

    def _assert_privacy(self, response) -> None:
        body = response.text
        self.assertNotIn(self.url, body)
        self.assertNotIn("secret-value", body)

    def test_target_401_maps_to_upstream_access_denied(self) -> None:
        with patch(
            "bintu_api.routes._enforce_robots",
            new=AsyncMock(),
        ), patch(
            "bintu_api.routes.fetch_html_document",
            side_effect=UpstreamHTTPError(401, "Unauthorized"),
        ):
            response = self._scrape()

        self.assertEqual(response.status_code, 502)
        payload = response.json()
        self.assertEqual(
            payload["detail"]["code"],
            "upstream_access_denied",
        )
        self.assertEqual(payload["detail"]["upstream_status"], 401)
        self._assert_privacy(response)

    def test_target_403_maps_to_upstream_access_denied(self) -> None:
        with patch(
            "bintu_api.routes._enforce_robots",
            new=AsyncMock(),
        ), patch(
            "bintu_api.routes.fetch_html_document",
            side_effect=UpstreamHTTPError(403, "Forbidden"),
        ):
            response = self._scrape()

        self.assertEqual(response.status_code, 502)
        payload = response.json()
        self.assertEqual(
            payload["detail"]["code"],
            "upstream_access_denied",
        )
        self.assertEqual(payload["detail"]["upstream_status"], 403)
        self._assert_privacy(response)

    def test_target_429_maps_to_upstream_access_denied(self) -> None:
        with patch(
            "bintu_api.routes._enforce_robots",
            new=AsyncMock(),
        ), patch(
            "bintu_api.routes.fetch_html_document",
            side_effect=UpstreamHTTPError(429, "Too Many Requests"),
        ):
            response = self._scrape()

        self.assertEqual(response.status_code, 502)
        payload = response.json()
        self.assertEqual(
            payload["detail"]["code"],
            "upstream_access_denied",
        )
        self.assertEqual(payload["detail"]["upstream_status"], 429)
        self._assert_privacy(response)

    def test_target_500_maps_to_upstream_http_error(self) -> None:
        with patch(
            "bintu_api.routes._enforce_robots",
            new=AsyncMock(),
        ), patch(
            "bintu_api.routes.fetch_html_document",
            side_effect=UpstreamHTTPError(500, "Internal Server Error"),
        ):
            response = self._scrape()

        self.assertEqual(response.status_code, 502)
        payload = response.json()
        self.assertEqual(
            payload["detail"]["code"],
            "upstream_http_error",
        )
        self.assertIn("500", payload["detail"]["message"])
        self._assert_privacy(response)

    def test_target_404_maps_to_upstream_http_error(self) -> None:
        with patch(
            "bintu_api.routes._enforce_robots",
            new=AsyncMock(),
        ), patch(
            "bintu_api.routes.fetch_html_document",
            side_effect=UpstreamHTTPError(404, "Not Found"),
        ):
            response = self._scrape()

        self.assertEqual(response.status_code, 502)
        payload = response.json()
        self.assertEqual(
            payload["detail"]["code"],
            "upstream_http_error",
        )
        self.assertIn("404", payload["detail"]["message"])
        self._assert_privacy(response)


if __name__ == "__main__":
    unittest.main(verbosity=2)