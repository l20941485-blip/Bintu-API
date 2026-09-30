import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from bintu_api.scraper import UpstreamHTTPError
from bintu_api.settings import Settings
from main import create_app


class ScraperApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app(Settings(api_key="", rapidapi_proxy_secret=""))
        self.client = TestClient(self.app)

    def test_read_root_and_health(self) -> None:
        gateway = self.client.get("/")
        health = self.client.get("/healthz")

        self.assertEqual(gateway.status_code, 200)
        self.assertEqual(gateway.json()["docs"], "/docs")
        self.assertEqual(health.json(), {"status": "ok"})

    def test_invalid_url_format(self) -> None:
        response = self.client.get("/api/v1/scrape/text", params={"url": "://example.com"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["code"], "invalid_or_unsafe_url")

    def test_scrape_text_extracts_content_without_live_network(self) -> None:
        html = (
            b"<html><body><header>Header noise</header>"
            b"<main>Useful <b>visible</b> text</main>"
            b"<script>script noise</script><style>.hidden { display: none; }</style>"
            b"<footer>Footer noise</footer><nav>Navigation noise</nav></body></html>"
        )
        with patch("bintu_api.routes.fetch_html", return_value=html):
            response = self.client.get(
                "/api/v1/scrape/text",
                params={"url": "https://example.com/page"},
                headers={"X-Request-ID": "test-trace-42"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["text"], "Useful visible text")
        self.assertEqual(response.headers["X-Request-ID"], "test-trace-42")

    def test_api_key_required_when_configured(self) -> None:
        app = create_app(Settings(api_key="local-test-secret", rapidapi_proxy_secret=""))
        client = TestClient(app)
        with patch("bintu_api.routes.fetch_html", return_value=b"<p>ok</p>"):
            denied = client.get("/api/v1/scrape/text", params={"url": "https://example.com"})
            wrong_length = client.get(
                "/api/v1/scrape/text",
                params={"url": "https://example.com"},
                headers={"X-API-Key": "short"},
            )
            accepted = client.get(
                "/api/v1/scrape/text",
                params={"url": "https://example.com"},
                headers={"X-API-Key": "local-test-secret"},
            )

        self.assertEqual(denied.status_code, 401)
        self.assertEqual(wrong_length.status_code, 401)
        self.assertEqual(accepted.status_code, 200)

    def test_rapidapi_proxy_secret_authentication(self) -> None:
        app = create_app(Settings(api_key="owner-key", rapidapi_proxy_secret="proxy-secret"))
        client = TestClient(app)
        with patch("bintu_api.routes.fetch_html", return_value=b"<p>ok</p>"):
            response = client.get(
                "/api/v1/scrape/text",
                params={"url": "https://example.com"},
                headers={
                    "X-RapidAPI-Proxy-Secret": "proxy-secret",
                    "X-RapidAPI-User": "subscriber-7",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["text"], "ok")
        self.assertIn("rapidapi:subscriber-7", app.state.rate_limiter._buckets)

    def test_paid_quotas_are_not_enforced_by_local_limiter(self) -> None:
        self.assertIn("RapidAPI owns paid-plan quota enforcement", self.app.state.rate_limiter.__class__.__doc__)

    def test_upstream_http_error_maps_to_502(self) -> None:
        with patch("bintu_api.routes.fetch_html", side_effect=UpstreamHTTPError(404, "Not Found")):
            response = self.client.get(
                "/api/v1/scrape/text",
                params={"url": "https://example.com/missing"},
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"]["code"], "upstream_http_error")

    def test_metrics_are_exposed_without_url_labels(self) -> None:
        self.client.get("/")
        response = self.client.get("/metrics", follow_redirects=False)

        self.assertEqual(response.status_code, 200)
        self.assertIn("bintu_http_requests_total", response.text)
        self.assertNotIn("example.com", response.text)
        self.assertNotIn("location", response.headers)

    def test_metrics_require_api_key_when_configured(self) -> None:
        app = create_app(Settings(api_key="metrics-secret", rapidapi_proxy_secret=""))
        client = TestClient(app)

        denied = client.get("/metrics")
        accepted = client.get("/metrics", headers={"X-API-Key": "metrics-secret"})

        self.assertEqual(denied.status_code, 401)
        self.assertEqual(accepted.status_code, 200)
        self.assertIn("bintu_http_requests_total", accepted.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)