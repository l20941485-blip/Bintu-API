"""Public discovery must work with production authentication enabled."""

import json
import re
import unittest

from fastapi.testclient import TestClient

from bintu_api.settings import Settings
from main import create_app


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app(Settings(
            api_key="test-only-key",
            rapidapi_proxy_secret="",
            require_auth=True,
        )))

    def test_robots_is_public_plain_text(self):
        response = self.client.get("/robots.txt")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response.headers["content-type"].startswith("text/plain")
        )
        self.assertIn("User-agent: *", response.text)
        self.assertIn("Allow: /", response.text)
        self.assertIn("/docs", response.text)

    def test_llms_is_public_and_documents_limits(self):
        response = self.client.get("/llms.txt")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response.headers["content-type"].startswith("text/plain")
        )
        for expected in (
            "1 MiB", "6,000", "HTML/XHTML", "bintu_scrape_text",
            "cache=false", "skip_cache=true",
        ):
            self.assertIn(expected, response.text)
        self.assertNotIn("test-only-key", response.text)

    def test_discovery_does_not_unlock_rest_extraction(self):
        self.client.get("/llms.txt")
        response = self.client.get(
            "/api/v1/scrape/text",
            params={"url": "https://example.com/"},
        )
        self.assertEqual(response.status_code, 401)



    def test_llms_json_example_has_plain_target_url(self):
        response = self.client.get("/llms.txt")
        self.assertEqual(response.status_code, 200)
        match = re.search(
            r"```json\s*(.*?)\s*```",
            response.text,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "Missing JSON example")
        example = json.loads(match.group(1))
        self.assertEqual(
            example["params"]["arguments"]["url"],
            "https://" + "example.com/",
        )


if __name__ == "__main__":
    unittest.main()
