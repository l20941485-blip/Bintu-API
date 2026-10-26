"""Health endpoint must expose non-secret deployed-build metadata."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from bintu_api.settings import Settings
from main import create_app


class HealthBuildMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            api_key="",
            rapidapi_proxy_secret="",
            render_js_enabled=False,
        )
        self.app = create_app(self.settings)
        self.client = TestClient(self.app)

    def test_health_returns_version_and_commit(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "RENDER_GIT_COMMIT": "8b180e6abc123",
                "RENDER_SERVICE_NAME": "bintu-api",
            },
        ):
            response = self.client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["version"], self.settings.service_version)
        self.assertEqual(payload["commit"], "8b180e6abc123")
        self.assertEqual(payload["environment"], "bintu-api")

    def test_health_omits_missing_optional_metadata(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "RENDER_GIT_COMMIT": "",
                "RENDER_SERVICE_NAME": "",
            },
        ):
            response = self.client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(
            payload["version"],
            self.settings.service_version,
        )
        self.assertIsNone(payload["commit"])
        self.assertIsNone(payload["environment"])

    def test_health_does_not_leak_secrets(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "RENDER_GIT_COMMIT": "8b180e6abc123",
                "API_KEY": "super-secret-key",
                "MCP_API_KEY": "super-secret-mcp-key",
                "SUPABASE_SERVICE_KEY": "super-secret-service-key",
            },
        ):
            response = self.client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("super-secret-key", response.text)
        self.assertNotIn("super-secret-mcp-key", response.text)
        self.assertNotIn("super-secret-service-key", response.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)