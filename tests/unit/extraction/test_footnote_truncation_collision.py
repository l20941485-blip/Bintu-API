from bintu_api.extraction.html_extract import extract_text_result

HTML = b"""
<html>
  <body>
    <main>
      <p>First <a href="/very/long/path/that/exceeds/the/limit?page=1">one</a></p>
      <p>Second <a href="/very/long/path/that/exceeds/the/limit?page=2">two</a></p>
    </main>
  </body>
</html>
"""


def test_truncated_footnotes_remain_distinct():
    result = extract_text_result(
        HTML,
        max_characters=1000,
        base_url="https://example.com/",
        links="footnotes",
        footnote_url_policy="truncated",
        max_footnote_url_length=40,
    )

    links = result.text.split("## Links", 1)[1]
    footnote_one = next(
        line for line in links.splitlines() if line.startswith("1. ")
    )
    footnote_two = next(
        line for line in links.splitlines() if line.startswith("2. ")
    )

    assert footnote_one != footnote_two
