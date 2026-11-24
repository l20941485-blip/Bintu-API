"""Tests for opt-in Trafilatura main-content extraction."""

from unittest.mock import patch

from bintu_api.extraction.html_extract import extract_main_content


def test_main_content_extraction_returns_markdown() -> None:
    html = b"<html><body><article>" + b"Word " * 100 + b"</article></body></html>"
    markdown = "# Title\n\n" + "Paragraph text. " * 30

    with patch("trafilatura.extract", return_value=markdown) as extract:
        text, applied = extract_main_content(
            html,
            10000,
            "utf-8",
            "https://example.com/",
        )

    assert applied is True
    assert text == markdown.strip()
    extract.assert_called_once_with(
        html.decode("utf-8"),
        url="https://example.com/",
        output_format="markdown",
        include_links=True,
        include_tables=True,
    )


def test_main_content_extraction_falls_back_on_empty_result() -> None:
    with patch("trafilatura.extract", return_value=""):
        text, applied = extract_main_content(
            b"<html><body></body></html>",
            10000,
            "utf-8",
            "https://example.com/",
        )

    assert applied is False
    assert text == ""


def test_main_content_extraction_falls_back_on_short_result() -> None:
    with patch("trafilatura.extract", return_value="Too short"):
        text, applied = extract_main_content(
            b"<html><body>Too short</body></html>",
            10000,
            "utf-8",
            "https://example.com/",
        )

    assert applied is False
    assert text == ""


def test_main_content_extraction_falls_back_on_error() -> None:
    with patch("trafilatura.extract", side_effect=RuntimeError("boom")):
        text, applied = extract_main_content(
            b"<html><body></body></html>",
            10000,
            "utf-8",
            "https://example.com/",
        )

    assert applied is False
    assert text == ""


def test_main_content_extraction_respects_character_cap() -> None:
    markdown = "x" * 500
    with patch("trafilatura.extract", return_value=markdown):
        text, applied = extract_main_content(
            b"<html><body></body></html>",
            250,
            "utf-8",
            "https://example.com/",
        )

    assert applied is True
    assert len(text) == 250


def test_main_content_truncation_closes_open_code_fence() -> None:
    markdown = "```python\n" + ("print('hello')\n" * 20) + "```"

    with patch("trafilatura.extract", return_value=markdown):
        text, applied = extract_main_content(
            b"<html><body><article>Example</article></body></html>",
            50,
            "utf-8",
            "https://example.com/docs",
        )

    assert applied is True
    assert len(text) <= 54
    assert text.count("```") % 2 == 0
    assert text.endswith("```")


def test_main_content_footnotes_truncate_long_urls() -> None:
    markdown = (
        "Intro text. " * 20
        + "See [docs](https://example.com/very/long/documentation/path/that/exceeds/limit) "
        + "and [again](https://example.com/very/long/documentation/path/that/exceeds/limit)."
    )

    with patch("trafilatura.extract", return_value=markdown):
        text, applied = extract_main_content(
            b"<html><body><article>Body</article></body></html>",
            5000,
            "utf-8",
            "https://example.com/",
            links="footnotes",
            footnote_url_policy="truncated",
            max_footnote_url_length=20,
        )

    assert applied is True
    assert "See docs [1] and again [1]." in text
    assert "## Links" in text
    assert "1. " in text
    assert "[URL truncated]" in text


def test_main_content_footnotes_preserve_full_urls_when_configured() -> None:
    full_url = "https://example.com/very/long/documentation/path/that/exceeds/limit"
    markdown = "Intro text. " * 20 + f"See [docs]({full_url})."

    with patch("trafilatura.extract", return_value=markdown):
        text, applied = extract_main_content(
            b"<html><body><article>Body</article></body></html>",
            5000,
            "utf-8",
            "https://example.com/",
            links="footnotes",
            footnote_url_policy="full",
            max_footnote_url_length=20,
        )

    assert applied is True
    assert "See docs [1]." in text
    assert "## Links" in text
    assert f"(<{full_url}>)" in text
    assert "[URL truncated]" not in text
