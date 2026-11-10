"""Unit tests for heading-based section selection."""

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
    assert result.sections[0]["text"] == "Alpha body"
    assert result.text == "Alpha body"


def test_selects_multiple_sections_in_document_order():
    result = select_sections(SAMPLE, ["beta", "alpha"], 100)

    assert [section["heading"] for section in result.sections] == [
        "Alpha",
        "Beta",
    ]
    assert [section["index"] for section in result.sections] == [0, 1]
    assert result.text == (
        "Alpha body\n\nBeta body\n\n## Gamma\nGamma body"
    )


def test_no_match_contract():
    result = select_sections(SAMPLE, ["missing"], 100)

    assert result.sections == []
    assert result.text == ""
    assert result.truncated is False


def test_empty_selector_list_contract():
    result = select_sections(SAMPLE, [], 100)

    assert result.sections == []
    assert result.text == ""
    assert result.truncated is False


def test_clipping_contract():
    long_text = "# Long\n" + ("x" * 100 + "\n") * 20

    result = select_sections(long_text, ["long"], 10)

    assert result.truncated is True
    assert len(result.text) <= 40


def test_multi_section_clipping_preserves_combined_text():
    text = (
        "# Alpha\n"
        + ("a" * 30 + "\n") * 3
        + "\n# Beta\n"
        + ("b" * 30 + "\n") * 3
        + "\n# Gamma\n"
        + ("c" * 30 + "\n") * 3
    )

    result = select_sections(text, ["alpha", "beta", "gamma"], 10)

    assert result.truncated is True
    assert len(result.sections) == 3
    assert result.text == "\n\n".join(
        section["text"] for section in result.sections
    )

