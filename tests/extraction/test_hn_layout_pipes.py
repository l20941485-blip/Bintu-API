"""HN layout cells must not introduce artificial pipe separators."""

import pytest

from bintu_api.extraction.html_extract import extract_text_result

HTML = b"""
<html>
<body>
<table id="hnmain">
  <tr><td>
    <table class="itemlist">
      <tr class="athing">
        <td class="title"><span class="rank">1.</span></td>
        <td class="votelinks"></td>
        <td class="title">
          <span class="titleline">
            <a href="https://example.com/story">Shell pipelines: A | B</a>
          </span>
        </td>
      </tr>
      <tr>
        <td colspan="2"></td>
        <td class="subtext">
          42 points by author |
          <a href="item?id=1">8 comments</a>
        </td>
      </tr>
    </table>
  </td></tr>
</table>
</body>
</html>
"""


@pytest.mark.parametrize("links", ["inline", "footnotes", "false"])
def test_hn_layout_cells_do_not_add_pipes(links):
    result = extract_text_result(
        HTML,
        max_characters=10000,
        base_url="https://news.ycombinator.com/",
        links=links,
    )

    lines = result.text.splitlines()
    story = next(line for line in lines if "Shell pipelines" in line)
    metadata = next(line for line in lines if "42 points" in line)

    assert story.startswith("1. Shell pipelines:")
    assert "A | B" in story
    assert metadata.startswith("42 points by author")
    assert "| 8 comments" in metadata
    assert lines.index(story) < lines.index(metadata)


def test_ordinary_table_keeps_cell_separators():
    result = extract_text_result(
        b"<table><tr><td>Alpha</td><td>Beta</td></tr></table>",
        max_characters=1000,
        links="false",
    )

    assert "Alpha | Beta" in result.text
