import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from bintu_api.scraper import FetchedHTML, UpstreamHTTPError
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
        with patch(
            "bintu_api.routes.fetch_html_document",
            return_value=FetchedHTML(body=html, charset=None),
        ):
            response = self.client.get(
                "/api/v1/scrape/text",
                params={"url": "https://example.com/page"},
                headers={"X-Request-ID": "test-trace-42"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["text"], "Useful visible text")
        self.assertEqual(response.headers["X-Request-ID"], "test-trace-42")

    def test_http_charset_is_used_and_retained_in_cache(self) -> None:
        fetched = FetchedHTML(body=b"<p>caf\xe9</p>", charset="iso-8859-1")
        with patch("bintu_api.routes.fetch_html_document", return_value=fetched) as fetch:
            first = self.client.get(
                "/api/v1/scrape/text",
                params={"url": "https://example.com/charset"},
            )
            second = self.client.get(
                "/api/v1/scrape/text",
                params={"url": "https://example.com/charset"},
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["text"], "café")
        self.assertEqual(second.json()["text"], "café")
        fetch.assert_called_once()

    def test_response_includes_truncation_and_resolves_relative_links(self) -> None:
        fetched = FetchedHTML(
            body=b"<main><p>Read <a href='/guide'>the guide</a>.</p></main>",
            charset=None,
            final_url="https://example.com/final/page",
        )
        with patch("bintu_api.routes.fetch_html_document", return_value=fetched):
            response = self.client.get(
                "/api/v1/scrape/text",
                params={"url": "https://example.com/original"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "url": "https://example.com/original",
                "text": "Read the guide (https://example.com/guide).",
                "truncated": False,
            },
        )

    def test_response_reports_when_text_is_truncated(self) -> None:
        settings = Settings(
            api_key="",
            rapidapi_proxy_secret="",
            max_text_characters=10,
        )
        client = TestClient(create_app(settings))
        with patch(
            "bintu_api.routes.fetch_html_document",
            return_value=FetchedHTML(body=b"<p>one two three four</p>", charset=None),
        ):
            response = client.get(
                "/api/v1/scrape/text",
                params={"url": "https://example.com/long"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["text"], "one two")
        self.assertTrue(response.json()["truncated"])

    def test_openapi_documents_scrape_response_contract(self) -> None:
        response = self.client.get("/openapi.json")

        self.assertEqual(response.status_code, 200)
        operation = response.json()["paths"]["/api/v1/scrape/text"]["get"]
        self.assertEqual(operation["summary"], "Extract readable text from a public web page")
        response_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
        schema_name = response_schema["$ref"].rsplit("/", 1)[-1]
        schema = response.json()["components"]["schemas"][schema_name]
        self.assertEqual(set(schema["required"]), {"url", "text", "truncated"})
        properties = schema["properties"]
        self.assertIn("True when", properties["truncated"]["description"])
        self.assertIn("character cap", properties["text"]["description"])

    def test_application_logs_and_metrics_exclude_scraped_content_and_target_url(self) -> None:
        target_url = "https://private.example/article?token=unique-target-secret"
        scraped_marker = "unique-scraped-content-marker"
        html = f"<main><p>{scraped_marker}</p></main>".encode()
        with patch(
            "bintu_api.routes.fetch_html_document",
            return_value=FetchedHTML(
                body=html,
                charset=None,
                final_url="https://private.example/article",
            ),
        ):
            with self.assertLogs("bintu_api.request", level="INFO") as captured:
                response = self.client.get(
                    "/api/v1/scrape/text",
                    params={"url": target_url},
                )

        self.assertEqual(response.status_code, 200)
        self.assertIn(scraped_marker, response.json()["text"])
        request_logs = "\n".join(captured.output)
        self.assertNotIn("private.example", request_logs)
        self.assertNotIn("unique-target-secret", request_logs)
        self.assertNotIn(scraped_marker, request_logs)

        metrics = self.client.get("/metrics")
        self.assertEqual(metrics.status_code, 200)
        self.assertNotIn("private.example", metrics.text)
        self.assertNotIn("unique-target-secret", metrics.text)
        self.assertNotIn(scraped_marker, metrics.text)

    def test_api_key_required_when_configured(self) -> None:
        app = create_app(Settings(api_key="local-test-secret", rapidapi_proxy_secret=""))
        client = TestClient(app)
        with patch(
            "bintu_api.routes.fetch_html_document",
            return_value=FetchedHTML(body=b"<p>ok</p>", charset=None),
        ):
            denied = client.get("/api/v1/scrape/text", params={"url": "https://example.com"})
            accepted = client.get(
                "/api/v1/scrape/text",
                params={"url": "https://example.com"},
                headers={"X-API-Key": "local-test-secret"},
            )

        self.assertEqual(denied.status_code, 401)
        self.assertEqual(accepted.status_code, 200)

    def test_rapidapi_proxy_secret_authentication(self) -> None:
        app = create_app(Settings(api_key="owner-key", rapidapi_proxy_secret="proxy-secret"))
        client = TestClient(app)
        with patch(
            "bintu_api.routes.fetch_html_document",
            return_value=FetchedHTML(body=b"<p>ok</p>", charset=None),
        ):
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
        with patch(
            "bintu_api.routes.fetch_html_document",
            side_effect=UpstreamHTTPError(404, "Not Found"),
        ):
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


if __name__ == "__main__":
    unittest.main(verbosity=2)