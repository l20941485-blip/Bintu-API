"""Tests for page_noise.py.

`extract()` is a TRIMMED copy of the relevant stages of
bintu_api.scraper.extract_text_result (title/heading comparison, anchor
flattening, heading and block boundaries). patched=False reproduces today's
output; patched=True applies the three integration edits.
"""
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from bs4.element import NavigableString

from bintu_api.page_noise import same_document, should_drop_title, strip_permalinks

BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt", "fieldset",
    "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr",
    "li", "main", "nav", "ol", "p", "pre", "section", "table", "tbody", "tfoot", "thead", "ul",
}
BASE = "https://docs.python.org/3/library/json.html"


def extract(html, patched, base_url=BASE):
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    if patched:
        strip_permalinks(soup)

    page_title = soup.title.get_text(" ", strip=True) if soup.title else ""
    if soup.title:
        soup.title.decompose()
    root = soup.find("article") or soup.find("main") or soup

    first_heading = root.find(["h1", "h2", "h3", "h4", "h5", "h6"])
    heading_text = first_heading.get_text(" ", strip=True) if first_heading else ""
    normalized_title = re.sub(r"\s+", " ", page_title).strip()
    normalized_heading = re.sub(r"\s+", " ", heading_text).strip()
    if patched:
        if normalized_title and should_drop_title(normalized_title, normalized_heading):
            normalized_title = ""
    elif normalized_title and normalized_title == normalized_heading:
        normalized_title = ""

    for anchor in soup.find_all("a", href=True):
        label = re.sub(r"\s+", " ", anchor.get_text()).strip()
        href = anchor["href"].strip()
        if not label or not href or not base_url:
            continue
        resolved = urlsplit(urljoin(base_url, href))
        if patched and same_document(base_url, resolved):
            anchor.replace_with(NavigableString(label))
            continue
        destination = urlunsplit((resolved.scheme, resolved.netloc, resolved.path, resolved.query, ""))
        if destination != label:
            anchor.replace_with(NavigableString(f"{label} ({destination})"))

    boundary = "\x00B\x00"
    for node in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        heading = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
        node.replace_with(NavigableString(f"{boundary}{'#' * int(node.name[1])} {heading}{boundary}"))
    for node in root.find_all(BLOCK_TAGS):
        node.insert_before(boundary)
        node.insert_after(boundary)

    lines = []
    for line in root.get_text().split(boundary):
        line = re.sub(r"\s+", " ", line).strip()
        line = re.sub(r"\s+([,.;:!?])", r"\1", line)
        if line:
            lines.append(line)
    if normalized_title:
        lines.insert(0, f"# {normalized_title}")
    return "\n".join(lines)


SPHINX = """
<html><head><title>json \u2014 JSON encoder and decoder \u2014 Python 3.15.2 documentation</title></head>
<body><main>
<section id="module-json">
<h1>json \u2014 JSON encoder and decoder<a class="headerlink" href="#module-json" title="Link to this heading">\u00b6</a></h1>
<p>See the standard (<a href="https://json.org">JSON</a>) spec.<a href="#id2">[1]</a></p>
<h2>Basic Usage<a class="headerlink" href="#basic-usage" title="Link to this heading">\u00b6</a></h2>
<dl class="py function"><dt class="sig" id="json.dump"><span class="sig-name">json.dump(obj, fp)</span><a class="headerlink" href="#json.dump" title="Link to this definition">\u00b6</a></dt>
<dd><p>Serialize obj to a stream. See <a href="/3/library/pickle.html#pickle-module">pickle</a>.</p></dd></dl>
</section></main></body></html>
"""


def test_baseline_reproduces_the_noise():
    out = extract(SPHINX, patched=False)
    lines = out.split("\n")
    assert lines[0].startswith("# json \u2014 JSON encoder and decoder \u2014 Python 3.15.2 documentation")
    assert any(l.startswith("# json \u2014 JSON encoder and decoder \u00b6 (") for l in lines)
    assert "[1] (https://docs.python.org/3/library/json.html)" in out


def test_patched_has_single_title_line_and_no_permalinks():
    out = extract(SPHINX, patched=True)
    lines = out.split("\n")
    assert lines[0] == "# json \u2014 JSON encoder and decoder"
    assert sum(1 for l in lines if l.startswith("# ")) == 1
    assert "\u00b6" not in out
    assert "## Basic Usage" in lines
    assert "json.dump(obj, fp)" in lines


def test_same_page_links_keep_only_their_label():
    out = extract(SPHINX, patched=True)
    assert "[1]" in out and "[1] (" not in out
    assert "(https://docs.python.org/3/library/json.html)" not in out


def test_external_and_other_page_links_are_still_annotated():
    out = extract(SPHINX, patched=True)
    assert "JSON (https://json.org)" in out
    assert "pickle (https://docs.python.org/3/library/pickle.html)" in out


def test_other_generators_are_covered():
    html = (
        "<main><h2>Install<a class='hash-link' href='#install' aria-label='Direct link to Install'></a></h2>"
        "<h2>Usage<a class='anchor' href='#usage'>#</a></h2>"
        "<h2>Notes<a href='#notes'>\U0001f517</a></h2>"
        "<h2>Config<a class='header-anchor' href='#config'>#</a></h2></main>"
    )
    out = extract(html, patched=True)
    assert out.split("\n") == ["## Install", "## Usage", "## Notes", "## Config"]


def test_glyph_link_outside_headings_is_not_removed():
    html = "<main><h2>Intro</h2><p>Jump to <a href='#note'>#</a> the note.</p></main>"
    assert "#" in extract(html, patched=True).split("\n")[1]


def test_title_with_extra_information_is_kept():
    html = "<html><head><title>Acme Docs home</title></head><body><main><h1>Install guide for Linux</h1></main></body></html>"
    assert extract(html, patched=True).split("\n")[0] == "# Acme Docs home"


def test_title_rules():
    assert should_drop_title("Install guide", "Install guide")
    assert should_drop_title("Install guide \u2014 Acme Docs", "Install guide")
    assert should_drop_title("Acme | Install guide", "Install guide")
    assert not should_drop_title("Reuters | Breaking News", "News")  # heading too short to trust
    assert not should_drop_title("Africa - BBC News", "Africa")
    assert not should_drop_title("", "Anything here")
    assert not should_drop_title("Title", "")


def test_same_document_rules():
    base = "https://docs.python.org/3/library/json.html"
    same = lambda url: same_document(base, urlsplit(url))
    assert same("https://docs.python.org/3/library/json.html#basic-usage")
    assert same("https://DOCS.python.org/3/library/json.html")
    assert not same("https://DOCS.python.org/3/library/json.html/")
    assert not same("https://docs.python.org/3/library/json.html?x=1")
    assert not same("https://docs.python.org/3/library/pickle.html")
    assert not same_document(None, urlsplit(base))


def _real_extract(html):
    from bintu_api.scraper import extract_text_result

    return extract_text_result(
        html.encode("utf-8"),
        20000,
        from_encoding="utf-8",
        base_url=BASE,
    ).text


def test_real_extractor_removes_sphinx_title_and_permalink_noise():
    out = _real_extract(SPHINX)
    lines = out.splitlines()
    assert lines[0] == "# json \u2014 JSON encoder and decoder"
    assert sum(line.startswith("# ") for line in lines) == 1
    assert "\u00b6" not in out
    assert "Python 3.15.2 documentation" not in out
    assert "## Basic Usage" in lines
    assert "json.dump(obj, fp)" in out
    assert "JSON (https://json.org)" in out
    assert "pickle (https://docs.python.org/3/library/pickle.html)" in out
    assert "[1]" in out


def test_real_extractor_preserves_meaningful_heading_anchor_text():
    out = _real_extract(
        "<main><h1><a class='anchor' href='#install'>"
        "Install guide</a></h1><p>Installation instructions.</p></main>"
    )
    assert "# Install guide" in out
    assert "Installation instructions." in out


def test_real_extractor_keeps_distinct_title():
    out = _real_extract(
        "<html><head><title>Acme Docs home</title></head>"
        "<body><main><h1>Install guide for Linux</h1>"
        "<p>Installation instructions.</p></main></body></html>"
    )
    assert out.splitlines()[0] == "# Acme Docs home"
    assert "# Install guide for Linux" in out


def test_title_substring_without_delimiter_is_not_dropped():
    assert not should_drop_title(
        "Install guide troubleshooting and known issues",
        "Install guide",
    )


def test_permalink_cleanup_preserves_code_content():
    soup = BeautifulSoup(
        "<pre><code><a class='headerlink' href='#sample'>"
        "\u00b6</a></code></pre>",
        "html.parser",
    )
    strip_permalinks(soup)
    assert soup.pre.get_text() == "\u00b6"


def test_real_extractor_removes_mkdocs_icon_and_duplicate_title():
    out = _real_extract(
        "<html><head><title>Writing Your Docs - MkDocs</title></head>"
        "<body><main>"
        "<h1>Writing your docs"
        "<a class='headerlink' href='#writing-your-docs'>\uf0c1</a>"
        "</h1>"
        "<h2>File layout<a href='#file-layout'>\uf0c1</a></h2>"
        "<p>Documentation layout instructions.</p>"
        "</main></body></html>"
    )
    assert out.splitlines()[0] == "# Writing your docs"
    assert sum(line.startswith("# ") for line in out.splitlines()) == 1
    assert "\uf0c1" not in out
    assert "## File layout" in out


def test_real_extractor_removes_vitepress_anchor_and_duplicate_title():
    out = _real_extract(
        "<html><head><title>Markdown Extensions | VitePress</title></head>"
        "<body><main>"
        "<h1>Markdown Extensions "
        "<a class='header-anchor' href='#markdown-extensions'>\u200b</a>"
        "</h1>"
        "<h2>Header Anchors<a href='#header-anchors'>\u200b</a></h2>"
        "<p>Headers support anchor links.</p>"
        "</main></body></html>"
    )
    assert out.splitlines()[0] == "# Markdown Extensions"
    assert sum(line.startswith("# ") for line in out.splitlines()) == 1
    assert "\u200b" not in out
    assert "## Header Anchors" in out


def test_real_extractor_keeps_same_document_labels_without_url():
    out = _real_extract(SPHINX)
    assert "[1]" in out
    assert f"[1] ({BASE})" not in out
    assert "JSON (https://json.org)" in out
    assert "pickle (https://docs.python.org/3/library/pickle.html)" in out


def test_real_extractor_preserves_heading_inside_same_document_link():
    out = _real_extract(
        "<main>"
        "<a href='#install'><h2>Install guide</h2></a>"
        "<p>Installation instructions.</p>"
        "</main>"
    )
    assert "## Install guide" in out.splitlines()
    assert f"({BASE})" not in out
