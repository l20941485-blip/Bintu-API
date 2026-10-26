"""Provenance URLs must never expose sensitive query parameters."""

from __future__ import annotations

import unittest

from bintu_api.routes import sanitize_url


class UrlSanitizationTests(unittest.TestCase):
    def test_api_key_is_removed(self) -> None:
        sanitized = sanitize_url(
            "https://example.com/page?api_key=secret-value&id=42"
        )

        self.assertEqual(sanitized, "https://example.com/page?id=42")
        self.assertNotIn("secret-value", sanitized)

    def test_token_is_removed(self) -> None:
        sanitized = sanitize_url(
            "https://example.com/page?token=abc123&q=python"
        )

        self.assertEqual(sanitized, "https://example.com/page?q=python")
        self.assertNotIn("abc123", sanitized)

    def test_secret_is_removed(self) -> None:
        sanitized = sanitize_url(
            "https://example.com/page?client_secret=xyz&q=python"
        )

        self.assertEqual(sanitized, "https://example.com/page?q=python")
        self.assertNotIn("xyz", sanitized)

    def test_password_is_removed(self) -> None:
        sanitized = sanitize_url(
            "https://example.com/page?password=hunter2&page=2"
        )

        self.assertEqual(sanitized, "https://example.com/page?page=2")
        self.assertNotIn("hunter2", sanitized)

    def test_utm_parameters_are_removed(self) -> None:
        sanitized = sanitize_url(
            "https://example.com/page?utm_source=newsletter&utm_campaign=launch&q=python"
        )

        self.assertEqual(sanitized, "https://example.com/page?q=python")
        self.assertNotIn("utm_source", sanitized)
        self.assertNotIn("utm_campaign", sanitized)

    def test_multiple_sensitive_parameters_are_removed(self) -> None:
        sanitized = sanitize_url(
            "https://example.com/page?key=a&token=b&secret=c&password=d&utm_term=e&keep=yes"
        )

        self.assertEqual(sanitized, "https://example.com/page?keep=yes")
        for leaked in ("=a", "=b", "=c", "=d", "=e"):
            self.assertNotIn(leaked, sanitized)

    def test_parameter_names_are_case_insensitive(self) -> None:
        sanitized = sanitize_url(
            "https://example.com/page?API_KEY=a&Token=b&SECRET=c"
        )

        self.assertEqual(sanitized, "https://example.com/page")
        self.assertNotIn("=a", sanitized)
        self.assertNotIn("=b", sanitized)
        self.assertNotIn("=c", sanitized)

    def test_url_without_query_is_unchanged(self) -> None:
        url = "https://example.com/page"

        self.assertEqual(sanitize_url(url), url)

    def test_fragment_is_preserved(self) -> None:
        sanitized = sanitize_url("https://example.com/page?token=abc#section")

        self.assertEqual(sanitized, "https://example.com/page#section")
        self.assertNotIn("abc", sanitized)


if __name__ == "__main__":
    unittest.main(verbosity=2)