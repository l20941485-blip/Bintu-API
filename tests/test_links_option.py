from bintu_api.scraper import extract_text_result


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
    html = f'<html><body><p><a href="{url}">Source</a></p></body></html>'.encode()

    result = extract_text_result(
        html,
        max_characters=1000,
        base_url="https://example.com/",
        links="footnotes",
    )

    link_line = next(line for line in result.text.splitlines() if line.startswith("1. ["))
    label = link_line.split("](", 1)[0][4:]
    assert len(label) <= 100
    assert label.startswith("example.com/very/long/path/")
    assert label.endswith("…")
    assert f"](<{url}>)" in link_line

    shorter_result = extract_text_result(
        html,
        max_characters=1000,
        base_url="https://example.com/",
        links="footnotes",
        footnote_display_max_length=40,
    )
    shorter_line = next(
        line for line in shorter_result.text.splitlines() if line.startswith("1. [")
    )
    shorter_label = shorter_line.split("](", 1)[0][4:]
    assert len(shorter_label) == 40
    assert shorter_label.endswith("…")
    assert f"](<{url}>)" in shorter_line


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
