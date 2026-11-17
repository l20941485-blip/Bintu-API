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
