import pytest

from bintu_api.context import TOKEN_METHOD, count_tokens
from bintu_api.reader import (
    DEFAULT_MAX_DOCUMENT_CHARACTERS,
    DocumentSnapshot,
    read_page,
)


def collect_pages(text, budget):
    snapshot = DocumentSnapshot(text)
    pages = []
    offset = 0

    for _ in range(len(text) + 1):
        page = read_page(snapshot, max_tokens=budget, offset=offset)
        pages.append(page)

        assert page.start_offset == offset
        assert page.text == text[offset:page.end_offset]
        assert page.approx_tokens == count_tokens(page.text)
        assert page.approx_tokens <= budget
        assert len(page.text) <= budget * 4
        assert page.token_method == TOKEN_METHOD

        if not page.has_more:
            assert page.end_offset == len(text)
            assert page.next_offset is None
            return pages

        assert page.end_offset > offset
        assert page.next_offset == page.end_offset
        offset = page.next_offset

    pytest.fail("Paging failed to terminate.")


def test_long_document_retains_end_marker():
    marker = "BINTU_END_MARKER_947"
    text = ("Documentation paragraph.\n" * 500) + marker

    assert len(text) > 6000
    pages = collect_pages(text, 64)

    assert len(pages) > 1
    assert "".join(page.text for page in pages) == text
    assert pages[-1].text.endswith(marker)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Short document.",
        " \n\t  ",
        "alpha  beta\n\n\tgamma\r\ndelta ",
        "https://example.org/" + "a" * 150,
        "VeryLongName" * 30 + " | value\n",
        "\u03b1\u03b2\u03b3\n\u4f60\u597d\n\U0001f642" * 40,
    ],
)
@pytest.mark.parametrize("budget", [1, 8, 32])
def test_pages_reconstruct_text_exactly(text, budget):
    pages = collect_pages(text, budget)

    assert "".join(page.text for page in pages) == text


def test_exact_budget_requires_no_continuation():
    page = read_page(DocumentSnapshot("abcdefgh"), max_tokens=2)

    assert page.text == "abcdefgh"
    assert page.approx_tokens == 2
    assert not page.has_more
    assert not page.boundary_split


def test_prefers_nearby_whitespace_boundary():
    page = read_page(
        DocumentSnapshot("alpha beta gamma"),
        max_tokens=3,
    )

    assert page.text == "alpha beta "
    assert page.next_offset == len("alpha beta ")
    assert not page.boundary_split


def test_oversized_unbroken_content_uses_hard_boundary():
    page = read_page(DocumentSnapshot("x" * 100), max_tokens=2)

    assert page.text == "x" * 8
    assert page.next_offset == 8
    assert page.boundary_split


def test_offset_at_end_returns_completed_page():
    page = read_page(
        DocumentSnapshot("abc"),
        max_tokens=1,
        offset=3,
    )

    assert page.text == ""
    assert page.approx_tokens == 0
    assert not page.has_more
    assert page.next_offset is None


@pytest.mark.parametrize("budget", [0, -1, True, 1.5, "8", None])
def test_rejects_invalid_budgets(budget):
    with pytest.raises(ValueError):
        read_page(DocumentSnapshot("abc"), max_tokens=budget)


@pytest.mark.parametrize("offset", [-1, 4, True, 1.5, "0", None])
def test_rejects_invalid_offsets(offset):
    with pytest.raises(ValueError):
        read_page(
            DocumentSnapshot("abc"),
            max_tokens=1,
            offset=offset,
        )


def test_accepts_document_at_retention_limit():
    snapshot = DocumentSnapshot(
        "x" * DEFAULT_MAX_DOCUMENT_CHARACTERS
    )

    assert len(snapshot.text) == DEFAULT_MAX_DOCUMENT_CHARACTERS


def test_rejects_oversized_document_without_silent_truncation():
    with pytest.raises(ValueError, match="character limit"):
        DocumentSnapshot(
            "x" * (DEFAULT_MAX_DOCUMENT_CHARACTERS + 1)
        )


@pytest.mark.parametrize("text", [None, 123, b"text"])
def test_rejects_non_string_documents(text):
    with pytest.raises(ValueError, match="string"):
        DocumentSnapshot(text)
