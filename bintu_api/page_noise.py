"""Remove three kinds of documentation noise from Bintu's extracted text.

1. Permalink links on headings and signatures:   "## Basic Usage ¶ (https://...)"
2. A duplicated title line:  "# json — ... — Python 3.15.2 documentation" followed by
   the page's own "# json — JSON encoder and decoder"
3. Same-page links that all turn into the page URL, e.g. "[1] (https://docs.python.org/3/library/json.html)"
   (the fragment is dropped, so every in-page link looks like a self-link)

Why it happens in bintu_api/scraper.py (extract_text_result):
  * Sphinx/MkDocs/etc. put <a class="headerlink" href="#x">¶</a> inside headings. The anchor
    loop rewrites it to "¶ (url)" BEFORE the heading text is read, so the heading becomes
    "json — JSON encoder and decoder ¶ (url)".
  * The title is dropped only when it EQUALS the first heading. Here it is
    "<heading> — Python 3.15.2 documentation", so it survives.

Integration (three small edits in extract_text_result):

    from bintu_api.page_noise import same_document, should_drop_title, strip_permalinks

    # (1) right after:  for node in soup(tags_to_remove): node.decompose()
    strip_permalinks(soup)

    # (2) replace   normalized_title == normalized_heading   with
    should_drop_title(normalized_title, normalized_heading)
    #     i.e.  if normalized_title and should_drop_title(normalized_title, normalized_heading):
    #               normalized_title = ""

    # (3) in the anchor loop, right after `resolved = urlsplit(urljoin(base_url, href))`
    if same_document(base_url, resolved):
        anchor.replace_with(NavigableString(label))
        continue
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

PERMALINK_SELECTOR = ", ".join(
    [
        "a.headerlink",  # Sphinx, MkDocs
        "a.header-anchor",  # VuePress / VitePress
        "a.anchor",  # GitHub-style
        "a.anchorjs-link",
        "a.hash-link",  # Docusaurus
        "a.permalink",
        "a.heading-anchor",
        "a.direct-link",
        "a[class*='permalink']",
        "a[class*='headerlink']",
        "a[aria-label='Permalink']",
        "a[title*='ermalink']",
        "a[title*='Link to this']",
    ]
)

_PERMALINK_GLYPHS = {"\u00b6", "#", "\u00a7", "\U0001f517", "\u00a4"}  # pilcrow, hash, section, link emoji
_HEADINGISH = ["h1", "h2", "h3", "h4", "h5", "h6", "dt", "caption", "summary"]


def strip_permalinks(soup) -> int:
    """Remove permalink anchors. Returns how many were removed.

    Class-based rules cover the common doc generators; the generic rule removes
    an anchor whose whole text is a permalink glyph, points inside the page, and
    sits in a heading / definition term / caption.
    """
    removed = 0
    for anchor in soup.select(PERMALINK_SELECTOR):
        if anchor.find_parent(["pre", "code"]):
            continue
        label = anchor.get_text(strip=True)
        if label and label not in _PERMALINK_GLYPHS:
            anchor.unwrap()
        else:
            anchor.decompose()
        removed += 1
    for anchor in soup.find_all("a", href=True):
        if (
            anchor.find_parent(["pre", "code"]) is None
            and anchor.get_text(strip=True) in _PERMALINK_GLYPHS
            and anchor["href"].strip().startswith("#")
            and anchor.find_parent(_HEADINGISH) is not None
        ):
            anchor.decompose()
            removed += 1
    return removed


def _norm(text: str) -> str:
    text = re.sub(r"[\u00b6#\u00a7]", " ", text.casefold())
    return re.sub(r"\s+", " ", text).strip()


def should_drop_title(title: str, first_heading: str) -> bool:
    """Suppress an exact title duplicate or a delimiter-separated site wrapper."""
    t, h = _norm(title), _norm(first_heading)
    if not t or not h:
        return False
    if t == h:
        return True
    if len(h) < 8:
        return False
    delimiter = r"(?:\s+[\u2014\u2013-]\s+|\s*\|\s*)"
    return bool(
        re.fullmatch(re.escape(h) + delimiter + r".+", t)
        or re.fullmatch(r".+" + delimiter + re.escape(h), t)
    )


def same_document(base_url: str | None, resolved) -> bool:
    """True when a resolved link points at the page being read (any fragment)."""
    if not base_url:
        return False
    base = urlsplit(base_url)

    def key(parts):
        return (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/") or "/", parts.query)

    return key(base) == key(resolved)
