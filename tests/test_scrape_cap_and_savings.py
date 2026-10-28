import re
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from bintu_api.robots import RobotsDecision
from bintu_api.scraper import FetchedHTML
from bintu_api.settings import Settings
from main import create_app


def _robots_patch():
    return patch(
        "bintu_api.routes.robots_decision",
        return_value=RobotsDecision(
            allowed=True,
            reason="disabled in tests",
            checked=False,
        ),
    )


def _html(paragraph_count: int, heading: str = "Latest updates") -> bytes:
    paragraphs = "".join(
        f"<p>Paragraph {index} contains enough repeated text to consume token budget.</p>"
        for index in range(paragraph_count)
    )
    return (
        b"<!doctype html><html><body><main>"
        b"<h1>Test article</h1>"
        + paragraphs.encode()
        + f"<h2>{heading}</h2><p>9</p>".encode()
        + b"</main></body></html>"
    )


class ScrapeCapAndSavingsTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = _robots_patch()
        self.robots_patch = patcher.start()
        self.addCleanup(patcher.stop)

        settings = Settings(
            api_key="",
            rapidapi_proxy_secret="",
        )
        self.app = create_app(settings)
        self.client = TestClient(self.app)

    def _scrape(self, html: bytes, **params):
        with patch(
            "bintu_api.routes.fetch_html_document",
            return_value=FetchedHTML(body=html, charset=None),
        ):
            return self.client.get("/api/v1/scrape/text", params=params)

    def test_scrape_honors_max_tokens_above_default_char_cap(self) -> None:
        response = self._scrape(
            _html(1000),
            url="https://example.com/large",
            mode="scrape",
            max_tokens=2000,
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertLessEqual(data["tokens"], 2000)
        self.assertIn(data["limiting_factor"], (None, "token_budget", "char_cap"))

    def test_scrape_savings_uses_returned_text(self) -> None:
        html = _html(1000)
        url = "https://example.com/large"

        full_response = self._scrape(html, url=url, mode="scrape")
        self.assertEqual(full_response.status_code, 200)
        full_tokens = full_response.json()["tokens"]

        budgeted_response = self._scrape(
            html,
            url=url,
            mode="scrape",
            max_tokens=250,
        )
        self.assertEqual(budgeted_response.status_code, 200)
        budgeted = budgeted_response.json()

        expected = max(0, full_tokens - budgeted["tokens"])
        self.assertEqual(budgeted["tokens_saved_estimate"], expected)

    def test_summarize_normalizes_headings_and_domains(self) -> None:
        html = (
            b"<!doctype html><html><body><main>"
            b"<h1>Example domains</h1>"
            b"<p>Visit example.org and icann.org for documentation.</p>"
            b"<h2>More information</h2>"
            b"<p>This page is for documentation examples.</p>"
            b"</main></body></html>"
        )

        response = self._scrape(
            html,
            url="https://example.com",
            mode="summarize",
            max_tokens=250,
        )

        self.assertEqual(response.status_code, 200)
        text = response.json()["text"]
        self.assertNotIn("example. org", text)
        self.assertNotIn("icann. org", text)
        self.assertIsNone(re.search(r"\S[ \t]+##", text))

    def test_truncation_does_not_leave_dangling_heading(self) -> None:
        response = self._scrape(
            _html(300),
            url="https://example.com/bbc-africa",
            mode="scrape",
            max_tokens=700,
        )

        self.assertEqual(response.status_code, 200)
        text = response.json()["text"].rstrip()
        self.assertFalse(text.endswith("##"))
        self.assertFalse(text.endswith("9"))


if __name__ == "__main__":
    unittest.main()


