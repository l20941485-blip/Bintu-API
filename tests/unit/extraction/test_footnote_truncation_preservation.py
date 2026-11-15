from bintu_api.extraction.html_extract import (
    _truncate_extracted_text_with_footnotes,
)


def test_footnote_block_survives_body_truncation():
    """A long body must not discard its trailing footnote block."""
    body = "Paragraph text. " * 500
    footnote_block = "\n\n## Links\n1. [Example](<https://example.com/>)"
    max_characters = 1000

    result = _truncate_extracted_text_with_footnotes(
        body,
        footnote_block,
        max_characters,
    )

    assert result.truncated is True
    assert "## Links" in result.text
    assert "https://example.com/" in result.text
    assert len(result.text) <= max_characters


def test_short_document_keeps_footnotes_without_truncation():
    body = "Short body text."
    footnote_block = "\n\n## Links\n1. [Example](<https://example.com/>)"

    result = _truncate_extracted_text_with_footnotes(
        body,
        footnote_block,
        1000,
    )

    assert result.truncated is False
    assert result.text == body + footnote_block


def test_no_footnotes_uses_normal_truncation():
    body = "Paragraph text. " * 500

    result = _truncate_extracted_text_with_footnotes(
        body,
        "",
        1000,
    )

    assert result.truncated is True
    assert "## Links" not in result.text
