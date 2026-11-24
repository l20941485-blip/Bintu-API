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



def test_selector_matches_heading_artifact():
    result = select_sections(
        "# Web scraping\n## History[edit]\nHistory body",
        ["history"],
        100,
    )

    assert len(result.sections) == 1
    assert result.sections[0]["heading"] == "History[edit]"
    assert result.sections[0]["text"] == "History body"


def test_selector_matches_heading_prefix():
    result = select_sections(
        "# Web scraping\n## History and development\nHistory body",
        ["history"],
        100,
    )

    assert len(result.sections) == 1
    assert result.sections[0]["heading"] == "History and development"
    assert result.sections[0]["text"] == "History body"


def test_selector_matches_heading_substring():
    result = select_sections(
        "# Web scraping\n## History and development\nHistory body",
        ["development"],
        100,
    )

    assert len(result.sections) == 1
    assert result.sections[0]["heading"] == "History and development"
    assert result.sections[0]["text"] == "History body"


def test_exact_heading_match_takes_priority():
    result = select_sections(
        "# Web scraping\n## History\nHistory body\n\n## History and development\nDevelopment body",
        ["history"],
        100,
    )

    assert len(result.sections) == 1
    assert result.sections[0]["heading"] == "History"
    assert result.sections[0]["text"] == "History body"


def test_token_budget_optimization_omits_low_value_sections():
    """When budget is tight, truncate combined text to fit within max_tokens."""
    text = (
        "# Introduction\nShort intro.\n\n"
        "## Background\n" + ("Long background text. " * 50) + "\n\n"
        "## Methodology\n" + ("Detailed methodology. " * 50) + "\n\n"
        "# Conclusion\nShort conclusion."
    )

    result = select_sections(
        text=text,
        sections=["Introduction", "Background", "Methodology", "Conclusion"],
        max_tokens=20,
    )

    assert result.truncated is True
    assert result.unmatched_sections == ()
    assert len(result.sections[0]["text"]) <= 80
    assert result.sections[-1]["text"] == ""
    assert result.text == "\n\n".join(s["text"] for s in result.sections)
    assert "Short intro." in result.text


def test_token_budget_generous_keeps_all():
    """When budget is large, all matched sections are retained untruncated."""
    text = "# A\nText A\n\n# B\nText B"

    result = select_sections(
        text=text,
        sections=["A", "B"],
        max_tokens=1000,
    )

    assert result.truncated is False
    assert result.unmatched_sections == ()
    assert len(result.sections) == 2
    assert "Text A" in result.text
    assert "Text B" in result.text

