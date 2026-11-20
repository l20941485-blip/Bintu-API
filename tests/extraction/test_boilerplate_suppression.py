from bintu_api.extraction.cleaner import suppress_boilerplate_lines


def test_removes_repeated_standalone_boilerplate_labels():
    text = "\n".join(
        [
            "# Article",
            "Meaningful paragraph that should remain.",
            "Skip to main content",
            "Another meaningful paragraph.",
            "Skip to main content",
            "Final meaningful paragraph.",
            "Skip to main content",
        ]
    )

    cleaned, removed = suppress_boilerplate_lines(text)

    assert removed == 3
    assert "Skip to main content" not in cleaned
    assert "Meaningful paragraph that should remain." in cleaned
    assert "Another meaningful paragraph." in cleaned
    assert "Final meaningful paragraph." in cleaned


def test_preserves_unique_navigation_and_reference_lines():
    text = "\n".join(
        [
            "# Documentation",
            "Overview",
            "Getting started",
            "API reference",
            "1. [example.com](https://example.com)",
            "2. [docs.example.com](https://docs.example.com)",
        ]
    )

    cleaned, removed = suppress_boilerplate_lines(text)

    assert removed == 0
    assert cleaned == text


def test_preserves_headings_lists_tables_and_footnotes():
    text = "\n".join(
        [
            "# Repeated heading",
            "- Repeated item",
            "* Repeated bullet",
            "| Repeated | table |",
            "1. Repeated footnote",
            "A meaningful sentence.",
        ]
    )

    cleaned, removed = suppress_boilerplate_lines(text)

    assert removed == 0
    assert cleaned == text


def test_does_not_remove_lines_below_threshold():
    text = "\n".join(
        [
            "Skip to main content",
            "Meaningful paragraph.",
            "Skip to main content",
            "Another meaningful paragraph.",
        ]
    )

    cleaned, removed = suppress_boilerplate_lines(text)

    assert removed == 0
    assert cleaned == text
