from bintu_api.extraction.context import _retain_referenced_footnotes


def test_selected_footnote_references_retain_their_links():
    """A selected section containing [n] retains only its referenced links."""
    selected = "The Content-Type header identifies the media type. [1]"
    raw = """# HTTP guide

## MIME types

The Content-Type header identifies the media type. [1]

## Links

1. [developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Content-Type](<https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Content-Type>)
2. [unrelated.example.com](<https://unrelated.example.com/>)
"""

    result = _retain_referenced_footnotes(selected, raw)

    assert "[1]" in result
    assert "## Links" in result
    assert (
        "developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Content-Type"
        in result
    )
    assert "unrelated.example.com" not in result


def test_selected_text_without_references_is_unchanged():
    selected = "Plain selected content without footnote references."
    raw = """## MIME types

Plain selected content without footnote references.

## Links

1. [example.com](<https://example.com/>)
"""

    assert _retain_referenced_footnotes(selected, raw) == selected
