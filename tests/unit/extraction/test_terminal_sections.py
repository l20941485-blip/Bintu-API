from bintu_api.extraction.cleaner import remove_terminal_sections


def test_removes_terminal_sections_from_first_match():
    text = (
        "# Guide\n\n"
        "Meaningful body content.\n\n"
        "## References\n\n"
        "[1] Example reference.\n\n"
        "## See also\n\n"
        "Related pages."
    )

    cleaned, removed = remove_terminal_sections(text)

    assert cleaned == "# Guide\n\nMeaningful body content."
    assert removed == 2


def test_preserves_document_without_terminal_section():
    text = "# Guide\n\nMeaningful body content.\n\n## Usage\n\nExample."

    cleaned, removed = remove_terminal_sections(text)

    assert cleaned == text
    assert removed == 0


def test_matches_terminal_headings_case_insensitively():
    text = "# Guide\n\nMeaningful body content.\n\n## REFERENCES\n\n[1] Example."

    cleaned, removed = remove_terminal_sections(text)

    assert cleaned == "# Guide\n\nMeaningful body content."
    assert removed == 1


def test_preserves_content_when_removal_would_empty_document():
    text = "## References\n\n[1] Example."

    cleaned, removed = remove_terminal_sections(text)

    assert cleaned == text
    assert removed == 0
