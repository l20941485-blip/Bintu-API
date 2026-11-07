from bintu_api.extraction.sections import select_sections


SAMPLE = """# Alpha
Alpha body

# Beta
Beta body

## Gamma
Gamma body
"""


def test_selects_single_section():
    result = select_sections(SAMPLE, ["alpha"], 100)

    assert len(result.sections) == 1
    assert result.sections[0]["heading"] == "Alpha"
    assert result.sections[0]["index"] == 0
    assert result.text == "# Alpha\nAlpha body"
    assert result.truncated is False


def test_selects_multiple_sections_in_document_order():
    result = select_sections(SAMPLE, ["beta", "alpha"], 100)

    assert [section["heading"] for section in result.sections] == [
        "Alpha",
        "Beta",
    ]
    assert result.text == (
        "# Alpha\nAlpha body\n\n"
        "# Beta\nBeta body\n\n## Gamma\nGamma body"
    )
    assert result.truncated is False


def test_deduplicates_selectors():
    result = select_sections(SAMPLE, ["alpha", "ALPHA"], 100)

    assert len(result.sections) == 1
    assert result.sections[0]["heading"] == "Alpha"


def test_matches_case_insensitively():
    result = select_sections(SAMPLE, ["ALPHA"], 100)

    assert result.sections[0]["heading"] == "Alpha"


def test_matches_whitespace_normalized_heading():
    result = select_sections(SAMPLE, ["  alpha  "], 100)

    assert result.sections[0]["heading"] == "Alpha"


def test_returns_empty_for_no_match():
    result = select_sections(SAMPLE, ["missing"], 100)

    assert result.sections == []
    assert result.text == ""
    assert result.truncated is False


def test_empty_selector_list_returns_empty():
    result = select_sections(SAMPLE, [], 100)

    assert result.sections == []
    assert result.text == ""
    assert result.truncated is False


def test_clips_long_sections():
    long_text = "# Long\n" + ("x" * 100 + "\n") * 20
    result = select_sections(long_text, ["long"], 10)

    assert result.truncated is True
    assert len(result.text) <= 40