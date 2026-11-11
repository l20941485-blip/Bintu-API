"""Tests for heading-based section selection in the Bintu extraction pipeline."""

from bintu_api.extraction.sections import SectionSelection, select_sections


def test_section_selection_shape():
    result = select_sections(
        "# Alpha\nAlpha body\n\n# Beta\nBeta body",
        ["alpha"],
        100,
    )

    assert isinstance(result, SectionSelection)
    assert isinstance(result.sections, list)
    assert isinstance(result.text, str)
    assert isinstance(result.truncated, bool)

    assert result.sections[0]["heading"] == "Alpha"
    assert result.sections[0]["level"] == 1
    assert result.sections[0]["index"] == 0
    assert result.sections[0]["text"] == "Alpha body"


def test_no_match_contract():
    result = select_sections(
        "# Alpha\nAlpha body",
        ["missing"],
        100,
    )

    assert result.sections == []
    assert result.text == ""
    assert result.truncated is False


def test_empty_selector_list_contract():
    result = select_sections(
        "# Alpha\nAlpha body",
        [],
        100,
    )

    assert result.sections == []
    assert result.text == ""
    assert result.truncated is False


def test_document_order_contract():
    result = select_sections(
        "# Alpha\nAlpha body\n\n# Beta\nBeta body",
        ["beta", "alpha"],
        100,
    )

    assert [section["index"] for section in result.sections] == [0, 1]
    assert result.text == "Alpha body\n\nBeta body"


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

