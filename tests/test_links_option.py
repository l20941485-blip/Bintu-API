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