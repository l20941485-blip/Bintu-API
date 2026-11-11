"""Test Links Option for Bintu.

This module owns a focused responsibility within the service and must remain isolated from unrelated transport or persistence concerns.

Important boundaries, invariants, and compatibility notes are documented here so the module stays focused on its owned behavior without drifting into unrelated routing or storage concerns.
"""

import pytest

from bintu_api.extraction.html_extract import extract_text_result
from bintu_api.scraper.fetcher import _compute_approx_tokens


def test_links_false_separates_link_and_span():
    html = b"""
    <html><body>
      <p>
        <a href="https://en.wikipedia.org/wiki/Flour">Flour</a>
        <a href="https://en.wikipedia.org/wiki/Water">water</a>
        <span>sourdough culture</span>
        <a href="https://en.wikipedia.org/wiki/Salt">salt</a>
      </p>
    </body></html>
    """

    result = extract_text_result(
        html,
        max_characters=1000,
        base_url="https://en.wikipedia.org/wiki/Sourdough",
        links="false",
    )

    assert "Flour water sourdough culture salt" in result.text
    assert "Flourwater" not in result.text
    assert "culturesalt" not in result.text


def test_links_footnotes_separates_adjacent_links():
    html = b"""
    <html><body>
      <p>
        <a href="https://en.wikipedia.org/wiki/Flour">Flour</a>
        <a href="https://en.wikipedia.org/wiki/Water">water</a>
        <span>sourdough culture</span>
        <a href="https://en.wikipedia.org/wiki/Salt">salt</a>
      </p>
    </body></html>
    """

    result = extract_text_result(
        html,
        max_characters=1000,
        base_url="https://en.wikipedia.org/wiki/Sourdough",
        links="footnotes",
    )

    assert "Flour [1] water [2] sourdough culture salt [3]" in result.text
    assert "Flour [1]water" not in result.text
    assert "culturesalt" not in result.text


def test_links_footnotes_deduplicates_exact_destinations():
    url = "https://example.com/report"
    html = f"""
    <html><body>
      <p><a href="{url}">First</a> <a href="{url}">Again</a></p>
    </body></html>
    """.encode()

    result = extract_text_result(
        html,
        max_characters=1000,
        base_url="https://example.com/",
        links="footnotes",
    )

    assert "First [1] Again [1]" in result.text
    assert result.text.count("1. [") == 1
    assert f"](<{url}>)" in result.text


def test_links_footnotes_deduplicates_fragment_only_differences():
    first_url = "https://example.com/report#overview"
    html = f"""
    <html><body>
      <p><a href="{first_url}">Overview</a>
      <a href="https://example.com/report#details">Details</a></p>
    </body></html>
    """.encode()

    result = extract_text_result(
        html,
        max_characters=1000,
        base_url="https://example.com/",
        links="footnotes",
    )

    assert "Overview [1] Details [1]" in result.text
    assert result.text.count("1. [") == 1
    assert f"](<{first_url}>)" in result.text
    assert "#details" not in result.text


def test_links_footnotes_deduplicates_trailing_slash_differences():
    first_url = "https://example.com/report/"
    html = f"""
    <html><body>
      <p><a href="{first_url}">First</a>
      <a href="https://example.com/report">Second</a></p>
    </body></html>
    """.encode()

    result = extract_text_result(
        html,
        max_characters=1000,
        base_url="https://example.com/",
        links="footnotes",
    )

    assert "First [1] Second [1]" in result.text
    assert result.text.count("1. [") == 1
    assert f"](<{first_url}>)" in result.text


def test_links_footnotes_normalizes_scheme_host_and_default_port_for_duplicates():
    first_url = "HTTPS://Example.COM:443/report"
    html = f"""
    <html><body>
      <p><a href="{first_url}">First</a>
      <a href="https://example.com/report">Second</a></p>
    </body></html>
    """.encode()

    result = extract_text_result(
        html,
        max_characters=1000,
        base_url="https://example.com/",
        links="footnotes",
    )

    assert "First [1] Second [1]" in result.text
    assert result.text.count("1. [") == 1
    assert f"](<{first_url}>)" in result.text


def test_links_footnotes_shorten_only_display_label_for_long_url():
    url = "https://example.com/" + ("very/long/path/" * 44) + ("x" * 13)
    assert len(url) == 693
    max_footnote_url_length = 100
    html = f'<html><body><p><a href="{url}">Source</a></p></body></html>'.encode()

    result = extract_text_result(
        html,
        max_characters=1000,
        base_url="https://example.com/",
        links="footnotes",
        footnote_url_policy="full",
        max_footnote_url_length=max_footnote_url_length,
    )

    link_line = next(line for line in result.text.splitlines() if line.startswith("1. ["))
    label = link_line.split("](", 1)[0][4:]
    target = link_line.split("](<", 1)[1][:-2]
    assert len(label) <= max_footnote_url_length
    assert label.startswith("example.com/very/long/path/")
    assert label.endswith("…")
    assert target == url

    shorter_result = extract_text_result(
        html,
        max_characters=1000,
        base_url="https://example.com/",
        links="footnotes",
        max_footnote_url_length=40,
    )
    shorter_line = next(
        line for line in shorter_result.text.splitlines() if line.startswith("1. ")
    )
    shorter_label = shorter_line.split(" [URL truncated]", 1)[0][3:]
    assert len(shorter_label) == 40
    assert shorter_label.endswith("…")
    assert url not in shorter_line
    assert shorter_line == f"1. {shorter_label} [URL truncated]"


def test_links_footnotes_default_policy_truncates_and_reduces_tokens():
    url = "https://example.com/" + ("very/long/path/" * 44) + ("x" * 13)
    assert len(url) == 693
    max_footnote_url_length = 100
    html = f'<html><body><p><a href="{url}">Source</a></p></body></html>'.encode()

    full_result = extract_text_result(
        html,
        max_characters=1000,
        base_url="https://example.com/",
        links="footnotes",
        footnote_url_policy="full",
        max_footnote_url_length=max_footnote_url_length,
    )
    default_result = extract_text_result(
        html,
        max_characters=1000,
        base_url="https://example.com/",
        links="footnotes",
        max_footnote_url_length=max_footnote_url_length,
    )
    explicit_truncated_result = extract_text_result(
        html,
        max_characters=1000,
        base_url="https://example.com/",
        links="footnotes",
        footnote_url_policy="truncated",
        max_footnote_url_length=max_footnote_url_length,
    )

    footnote_output = default_result.text.split("## Links\n", 1)[1]
    footnote_line = footnote_output.strip()
    visible_label = footnote_line.split(" [URL truncated]", 1)[0][3:]
    assert len(visible_label) <= max_footnote_url_length
    assert visible_label.endswith("…")
    assert url not in footnote_output
    assert footnote_output.count("[URL truncated]") == 1
    assert "`" not in footnote_output
    assert footnote_line == f"1. {visible_label} [URL truncated]"
    assert explicit_truncated_result.text == default_result.text
    assert _compute_approx_tokens(default_result.text) < _compute_approx_tokens(
        full_result.text
    )


def test_legacy_footnote_display_length_alias_is_supported():
    url = "https://example.com/" + ("path/" * 25)
    html = f'<html><body><p><a href="{url}">Source</a></p></body></html>'.encode()

    result = extract_text_result(
        html,
        max_characters=1000,
        base_url="https://example.com/",
        links="footnotes",
        footnote_display_max_length=20,
    )

    footnote_line = next(line for line in result.text.splitlines() if line.startswith("1. "))
    label = footnote_line.split(" [URL truncated]", 1)[0][3:]
    assert len(label) == 20
    assert label.endswith("…")
    assert footnote_line == f"1. {label} [URL truncated]"


def test_footnote_length_options_reject_conflicting_values():
    html = (
        b'<html><body><p><a href="https://example.com/long/path">'
        b"Source</a></p></body></html>"
    )

    with pytest.raises(
        ValueError,
        match="Specify either max_footnote_url_length or footnote_display_max_length",
    ):
        extract_text_result(
            html,
            max_characters=1000,
            base_url="https://example.com/",
            links="footnotes",
            max_footnote_url_length=40,
            footnote_display_max_length=20,
        )


def test_links_footnotes_separates_footnote_and_span():
    html = b"""
    <html><body>
      <p>
        <a href="https://en.wikipedia.org/wiki/Flour">Flour</a>
        <a href="https://en.wikipedia.org/wiki/Water">water</a>
        <span>sourdough culture</span>
        <a href="https://en.wikipedia.org/wiki/Salt">salt</a>
      </p>
    </body></html>
    """

    result = extract_text_result(
        html,
        max_characters=1000,
        base_url="https://en.wikipedia.org/wiki/Sourdough",
        links="footnotes",
    )

    assert "Flour [1] water [2] sourdough culture salt [3]" in result.text
    assert "Flour [1]water" not in result.text
    assert "water [2]sourdough" not in result.text
    assert "culturesalt" not in result.text

def test_links_inline_preserves_urls():
    html = b"""
    <html><body>
      <p><a href="https://en.wikipedia.org/wiki/Flour">Flour</a></p>
    </body></html>
    """

    result = extract_text_result(
        html,
        max_characters=1000,
        base_url="https://en.wikipedia.org/wiki/Sourdough",
        links="inline",
    )

    assert "Flour (https://en.wikipedia.org/wiki/Flour)" in result.text



