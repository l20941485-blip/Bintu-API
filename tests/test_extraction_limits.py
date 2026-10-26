"""Text extraction must respect limits and avoid unsafe output expansion."""

from __future__ import annotations

import unittest

from bintu_api.scraper import extract_text_result


class ExtractionLimitTests(unittest.TestCase):
    def test_returns_short_text_without_truncation(self) -> None:
        result = extract_text_result(
            b"<html><body><p>Hello world</p></body></html>",
            max_characters=100,
        )

        self.assertEqual(result.text, "Hello world")
        self.assertFalse(result.truncated)

    def test_truncates_long_text(self) -> None:
        html = b"<html><body><p>" + b"word " * 100 + b"</p></body></html>"
        result = extract_text_result(html, max_characters=20)

        self.assertTrue(result.truncated)
        self.assertLessEqual(len(result.text), 20)

    def test_truncation_prefers_word_boundary(self) -> None:
        html = b"<html><body><p>alpha beta gamma delta</p></body></html>"
        result = extract_text_result(html, max_characters=15)

        self.assertTrue(result.truncated)
        self.assertEqual(result.text, "alpha beta")

    def test_exact_length_is_not_truncated(self) -> None:
        html = b"<html><body><p>abcdefghij</p></body></html>"
        result = extract_text_result(html, max_characters=10)

        self.assertEqual(result.text, "abcdefghij")
        self.assertFalse(result.truncated)

    def test_title_is_included_once(self) -> None:
        html = (
            b"<html><head><title>Page Title</title></head>"
            b"<body><h1>Page Title</h1><p>Body</p></body></html>"
        )
        result = extract_text_result(html, max_characters=100)

        self.assertEqual(result.text, "# Page Title\nBody")

    def test_title_and_different_heading_are_both_included(self) -> None:
        html = (
            b"<html><head><title>Page Title</title></head>"
            b"<body><h1>Different Heading</h1><p>Body</p></body></html>"
        )
        result = extract_text_result(html, max_characters=100)

        self.assertIn("# Page Title", result.text)
        self.assertIn("Different Heading", result.text)
        self.assertIn("Body", result.text)


class ExtractionLinkSafetyTests(unittest.TestCase):
    def test_annotates_relative_http_link(self) -> None:
        html = b'<html><body><a href="/page">Read more</a></body></html>'
        result = extract_text_result(
            html,
            max_characters=500,
            base_url="https://example.com/start",
        )

        self.assertEqual(
            result.text,
            "Read more (https://example.com/page)",
        )

    def test_annotates_absolute_https_link(self) -> None:
        html = (
            b'<html><body><a href="https://example.org/page">'
            b"External</a></body></html>"
        )
        result = extract_text_result(
            html,
            max_characters=500,
            base_url="https://example.com/start",
        )

        self.assertEqual(
            result.text,
            "External (https://example.org/page)",
        )

    def test_does_not_annotate_link_when_destination_equals_label(self) -> None:
        html = (
            b'<html><body><a href="https://example.com/page">'
            b"https://example.com/page</a></body></html>"
        )
        result = extract_text_result(
            html,
            max_characters=500,
            base_url="https://example.com/start",
        )

        self.assertEqual(result.text, "https://example.com/page")

    def test_skips_javascript_links(self) -> None:
        html = (
            b'<html><body><a href="javascript:alert(1)">Click</a>'
            b"</body></html>"
        )
        result = extract_text_result(
            html,
            max_characters=500,
            base_url="https://example.com/start",
        )

        self.assertEqual(result.text, "Click")

    def test_skips_data_links(self) -> None:
        html = (
            b'<html><body><a href="data:text/plain,hello">Download</a>'
            b"</body></html>"
        )
        result = extract_text_result(
            html,
            max_characters=500,
            base_url="https://example.com/start",
        )

        self.assertEqual(result.text, "Download")

    def test_skips_links_with_credentials(self) -> None:
        html = (
            b'<html><body><a href="https://user:pass@example.com/page">'
            b"Private</a></body></html>"
        )
        result = extract_text_result(
            html,
            max_characters=500,
            base_url="https://example.com/start",
        )

        self.assertEqual(result.text, "Private")

    def test_ignores_links_without_base_url(self) -> None:
        html = b'<html><body><a href="/page">Read more</a></body></html>'
        result = extract_text_result(html, max_characters=500)

        self.assertEqual(result.text, "Read more")


class ExtractionVisibilityTests(unittest.TestCase):
    def test_removes_script_and_style(self) -> None:
        html = (
            b"<html><head><style>.hidden { display: none; }</style></head>"
            b"<body><script>evil()</script><p>Visible</p></body></html>"
        )
        result = extract_text_result(html, max_characters=500)

        self.assertEqual(result.text, "Visible")

    def test_removes_hidden_elements(self) -> None:
        html = (
            b"<html><body>"
            b'<p hidden>Hidden</p>'
            b'<p aria-hidden="true">Also hidden</p>'
            b'<p style="display: none">CSS hidden</p>'
            b"<p>Visible</p>"
            b"</body></html>"
        )
        result = extract_text_result(html, max_characters=500)

        self.assertEqual(result.text, "Visible")

    def test_removes_nav_by_default(self) -> None:
        html = (
            b"<html><body><nav>Menu</nav><main><p>Article</p></main>"
            b"</body></html>"
        )
        result = extract_text_result(html, max_characters=500)

        self.assertEqual(result.text, "Article")

    def test_can_include_nav_when_requested(self) -> None:
        html = (
            b"<html><body><nav>Menu</nav><main><p>Article</p></main>"
            b"</body></html>"
        )
        result = extract_text_result(
            html,
            max_characters=500,
            include_nav=True,
        )

        self.assertIn("Menu", result.text)
        self.assertIn("Article", result.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)