import pytest

from bintu_api.reader import (
    DEFAULT_MAX_DOCUMENT_CHARACTERS,
    read_page,
)
from bintu_api.reader_extraction import (
    ReaderDocumentEmpty,
    ReaderDocumentTooLarge,
    snapshot_from_document,
)
from bintu_api.scraper import FetchedHTML, extract_text_result


URL = "https://example.com/start"


def document(html, final_url=URL):
    return FetchedHTML(
        body=html.encode("utf-8"),
        charset="utf-8",
        final_url=final_url,
    )


def extract(html, final_url=URL, **options):
    return snapshot_from_document(
        document(html, final_url),
        requested_url=URL,
        **options,
    )


def test_long_html_retains_tail_and_can_be_paged_losslessly():
    marker = "BINTU_HTML_END_MARKER"
    html = (
        "<html><body><main>"
        + "<p>Documentation paragraph.</p>" * 500
        + f"<p>{marker}</p>"
        + "</main></body></html>"
    )
    fetched = document(html)
    snapshot = snapshot_from_document(fetched, requested_url=URL)

    legacy = extract_text_result(
        fetched.body,
        6000,
        from_encoding=fetched.charset,
        base_url=fetched.final_url,
    )
    assert legacy.truncated
    assert marker not in legacy.text
    assert len(snapshot.text) > 6000
    assert snapshot.text.endswith(marker)

    parts = []
    offset = 0
    for _ in range(len(snapshot.text) + 1):
        page = read_page(snapshot, max_tokens=32, offset=offset)
        assert page.approx_tokens <= 32
        parts.append(page.text)

        if page.next_offset is None:
            break
        assert page.next_offset > offset
        offset = page.next_offset
    else:
        pytest.fail("Paging failed to terminate.")

    assert "".join(parts) == snapshot.text


def test_exact_retention_limit_is_accepted():
    text = "x" * DEFAULT_MAX_DOCUMENT_CHARACTERS
    snapshot = extract(f"<main><p>{text}</p></main>")

    assert snapshot.text == text


@pytest.mark.parametrize("extra", [1, 100])
def test_oversized_unbroken_text_is_rejected(extra):
    text = "x" * (DEFAULT_MAX_DOCUMENT_CHARACTERS + extra)

    with pytest.raises(ReaderDocumentTooLarge):
        extract(f"<main><p>{text}</p></main>")


def test_oversized_text_cannot_hide_behind_word_boundary_truncation():
    text = (
        "x" * (DEFAULT_MAX_DOCUMENT_CHARACTERS - 10)
        + " "
        + "tail " * 100
    )

    with pytest.raises(ReaderDocumentTooLarge):
        extract(f"<main><p>{text}</p></main>")


@pytest.mark.parametrize(
    "html",
    [
        "<html><body></body></html>",
        "<main>   </main>",
        "<html><body><script>alert(1)</script></body></html>",
        "<html><head><style>body { color: red; }</style></head>"
        "<body></body></html>",
    ],
)
def test_empty_extraction_is_rejected(html):
    with pytest.raises(ReaderDocumentEmpty):
        extract(html)


def test_relative_links_use_final_redirect_url():
    snapshot = extract(
        '<main><p><a href="authentication">Read authentication</a></p></main>',
        final_url="https://docs.example.org/guide/",
    )

    assert (
        "Read authentication "
        "(https://docs.example.org/guide/authentication)"
    ) in snapshot.text
    assert "https://example.com/authentication" not in snapshot.text


def test_navigation_is_excluded_by_default_and_can_be_included():
    html = (
        "<html><body><nav>Navigation item</nav>"
        "<main><p>Document body</p></main></body></html>"
    )

    default = extract(html)
    included = extract(html, include_nav=True)

    assert "Navigation item" not in default.text
    assert "Document body" in default.text
    assert "Navigation item" in included.text
    assert "Document body" in included.text


def test_preserves_existing_heading_and_table_extraction():
    html = (
        "<main><h1>Reference</h1>"
        "<table><tr><th>Name</th><th>Value</th></tr>"
        "<tr><td>Alpha</td><td>1</td></tr></table></main>"
    )

    snapshot = extract(html)

    assert "# Reference" in snapshot.text
    assert "Name | Value" in snapshot.text
    assert "Alpha | 1" in snapshot.text
