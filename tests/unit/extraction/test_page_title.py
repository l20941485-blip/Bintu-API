"""Tests for page-title extraction."""

from bs4 import BeautifulSoup

from bintu_api.extraction.html_extract import (
    extract_html_metadata,
    extract_page_title,
)


def test_extracts_normalized_page_title_and_source():
    soup = BeautifulSoup(
        b"""
        <html>
          <head><title>  Example Page  </title></head>
          <body><p>Content</p></body>
        </html>
        """,
        "html.parser",
        from_encoding="utf-8",
    )

    page_title, page_title_source = extract_page_title(soup)

    assert page_title == "Example Page"
    assert page_title_source == "html_title"


def test_returns_none_and_none_source_when_title_is_absent():
    soup = BeautifulSoup(
        b"<html><body><p>Content</p></body></html>",
        "html.parser",
    )

    page_title, page_title_source = extract_page_title(soup)

    assert page_title is None
    assert page_title_source == "none"


def test_html_metadata_returns_page_title():
    html = b"""
    <html lang="en">
      <head>
        <title>Example Page</title>
        <link rel="canonical" href="https://example.com/canonical">
      </head>
      <body><p>Content</p></body>
    </html>
    """

    canonical_url, language, page_title, page_title_source = extract_html_metadata(
        html,
        from_encoding="utf-8",
    )

    assert canonical_url == "https://example.com/canonical"
    assert language == "en"
    assert page_title == "Example Page"
    assert page_title_source == "html_title"
