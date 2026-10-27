"""Comment-thread pages must preserve discussion and omit site furniture."""

from bintu_api.scraper import extract_text


HTML = b"""
<html>
  <body>
    <table id="hnmain">
      <tr><td>
        <span class="titleline"><a href="/x">Discussion title</a></span>
        <a href="/login">login</a>
      </td></tr>
      <tr><td>
        <div class="commtext">This is the useful comment text.</div>
      </td></tr>
      <tr><td>
        <a href="/newsguidelines.html">Guidelines</a>
        <a href="/newsfaq.html">FAQ</a>
        <a href="https://www.ycombinator.com/apply/">Apply to YC</a>
      </td></tr>
    </table>
  </body>
</html>
"""


def test_comment_thread_prefers_comments_and_title() -> None:
    text = extract_text(HTML, max_characters=6000)

    assert "Discussion title" in text
    assert "This is the useful comment text." in text
    assert "login" not in text
    assert "Guidelines" not in text
    assert "FAQ" not in text
    assert "Apply to YC" not in text