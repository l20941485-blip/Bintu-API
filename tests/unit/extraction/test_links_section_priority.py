
from bintu_api.extraction.context import _retain_referenced_footnotes


def test_links_section_is_preferred_over_references():
    """A generated Links section must be used when both sections exist."""
    selected = "Archaeologists found evidence of flour production. [15]"
    raw = """# Flour

## History

Archaeologists found evidence of flour production. [15]

## References

↑ Unrelated reference text.

## Links

15. [example.com](<https://example.com/>)
16. [unrelated.example.com](<https://unrelated.example.com/>)
"""

    result = _retain_referenced_footnotes(selected, raw)

    assert "## Links" in result
    assert "example.com" in result
    assert "unrelated.example.com" not in result
    assert "Unrelated reference text." not in result


def test_references_section_is_used_when_links_is_absent():
    selected = "Archaeologists found evidence of flour production. [15]"
    raw = """# Flour

## History

Archaeologists found evidence of flour production. [15]

## References

15. Reference fifteen.
16. Unrelated reference sixteen.
"""

    result = _retain_referenced_footnotes(selected, raw)

    assert "## References" in result
    assert "Reference fifteen." in result
    assert "Unrelated reference sixteen." not in result
