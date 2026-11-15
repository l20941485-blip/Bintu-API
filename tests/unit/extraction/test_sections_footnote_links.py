from bintu_api.extraction.context import _retain_referenced_footnotes


def test_selected_footnote_references_retain_links_section():
    """A selected [n] reference retains its matching Links entry."""
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


def test_selected_footnote_references_retain_references_section():
    """A selected [n] reference retains its matching References entry."""
    selected = "Archaeologists found evidence of flour production. [15]"
    raw = """# Flour

## History

Archaeologists found evidence of flour production. [15]

## References

15.
↑ Reference fifteen.

16.
↑ Unrelated reference sixteen.
"""

    result = _retain_referenced_footnotes(selected, raw)

    assert "[15]" in result
    assert "## References" in result
    assert "Reference fifteen." in result
    assert "Unrelated reference sixteen." not in result


def test_selected_text_without_references_is_unchanged():
    selected = "Plain selected content without footnote references."
    raw = """## MIME types

Plain selected content without footnote references.

## References

15.
↑ Reference fifteen.
"""

    assert _retain_referenced_footnotes(selected, raw) == selected
