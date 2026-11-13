from bintu_api.extraction.html_extract import extract_text_result

HTML = b"""
<html>
  <body>
    <main>
      <p>First <a href="/a?page=1">one</a></p>
      <p>Second <a href="/b?page=2">two</a></p>
    </main>
  </body>
</html>
"""


def test_footnotes_are_deterministic():
    first = extract_text_result(
        HTML,
        max_characters=1000,
        base_url="https://example.com/",
        links="footnotes",
        footnote_url_policy="truncated",
        max_footnote_url_length=40,
    )

    second = extract_text_result(
        HTML,
        max_characters=1000,
        base_url="https://example.com/",
        links="footnotes",
        footnote_url_policy="truncated",
        max_footnote_url_length=40,
    )

    assert first.text == second.text
