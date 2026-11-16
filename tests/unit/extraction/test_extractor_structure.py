"""Regression tests for extractor structure and content-root selection."""

from __future__ import annotations

import unittest
import unittest.mock

from bs4 import BeautifulSoup

from bintu_api.extraction.html_extract import (
    extract_canonical_url,
    extract_language,
    extract_text_result,
)


class ExtractorStructureTests(unittest.TestCase):
    def extract(self, html: str, *, max_characters: int = 10000):
        return extract_text_result(
            html.encode("utf-8"),
            max_characters=max_characters,
            base_url="https://example.com/",
        )

    def test_homepage_with_small_hero_article_keeps_other_stories(self):
        html = """
        <html><body>
          <article>
            <h1>Hero headline</h1>
            <p>Hero description.</p>
          </article>
          <section>
            <h2>Second story</h2>
            <p>Second description.</p>
          </section>
          <section>
            <h2>Third story</h2>
            <p>Third description.</p>
          </section>
          <section>
            <h2>Fourth story</h2>
            <p>Fourth description.</p>
          </section>
        </body></html>
        """
        result = self.extract(html)
        self.assertFalse(result.truncated)
        for expected in (
            "Hero headline",
            "Second story",
            "Third story",
            "Fourth story",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, result.text)

    def test_large_main_container_is_preferred(self):
        html = """
        <html><body>
          <nav>Navigation navigation navigation</nav>
          <main>
            <h1>Article headline</h1>
            <p>Article body.</p>
          </main>
          <footer>Footer footer footer</footer>
        </body></html>
        """
        result = self.extract(html)
        self.assertIn("Article headline", result.text)
        self.assertIn("Article body.", result.text)

    def test_card_link_containing_heading_and_description_keeps_structure(self):
        html = """
        <html><body>
          <a href="https://example.com/story">
            <h2>Headline</h2>
            <p>Blurb</p>
          </a>
        </body></html>
        """
        result = self.extract(html)
        self.assertIn("Headline", result.text)
        self.assertIn("Blurb", result.text)
        self.assertIn("https://example.com/story", result.text)
        self.assertNotIn("HeadlineBlurb", result.text)
        self.assertNotIn("Headline (https://example.com/story)Blurb", result.text)

    def test_inline_link_still_annotates_destination(self):
        html = """
        <html><body>
          <p>Read the <a href="https://example.com/report">report</a> today.</p>
        </body></html>
        """
        result = self.extract(html)
        self.assertIn("report (https://example.com/report)", result.text)

    def test_trafilatura_fallback_runs_for_sparse_html(self):
        html = """
        <html><body><script>ignored</script></body></html>
        """
        with unittest.mock.patch(
            "bintu_api.extraction.html_extract._trafilatura_fallback",
            return_value="A much longer fallback article body with enough content to replace the sparse BeautifulSoup extraction result.",
        ) as fallback:
            result = self.extract(html)

        fallback.assert_called_once()
        self.assertIn(
            "A much longer fallback article body",
            result.text,
        )

    def test_trafilatura_fallback_does_not_replace_normal_extraction(self):
        html = """
        <html><body>
          <main>
            <h1>Article headline</h1>
            <p>Article body.</p>
          </main>
        </body></html>
        """
        with unittest.mock.patch(
            "bintu_api.extraction.html_extract._trafilatura_fallback",
        ) as fallback:
            result = self.extract(html)

        self.assertIn("Article headline", result.text)
        self.assertIn("Article body.", result.text)


class CanonicalAndLanguageTests(unittest.TestCase):
    def parse(self, html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "html.parser")

    def test_canonical_url_from_link_rel_canonical(self):
        soup = self.parse(
            "<html><head>"
            '<link rel="canonical" href="https://example.com/canonical">'
            "</head><body><main><p>Body</p></main></body></html>",
        )

        self.assertEqual(
            extract_canonical_url(soup),
            "https://example.com/canonical",
        )

    def test_canonical_url_is_none_when_link_absent(self):
        soup = self.parse(
            "<html><head></head><body><main><p>Body</p></main></body></html>",
        )

        self.assertIsNone(extract_canonical_url(soup))

    def test_language_from_html_lang(self):
        soup = self.parse(
            '<html lang="fr"><body><main><p>Body</p></main></body></html>',
        )

        self.assertEqual(extract_language(soup), "fr")

    def test_language_falls_back_to_meta_content_language(self):
        soup = self.parse(
            "<html><head>"
            '<meta http-equiv="content-language" content="de">'
            "</head><body><main><p>Body</p></main></body></html>",
        )

        self.assertEqual(extract_language(soup), "de")

    def test_language_is_none_when_neither_present(self):
        soup = self.parse(
            "<html><head></head><body><main><p>Body</p></main></body></html>",
        )

        self.assertIsNone(extract_language(soup))
