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
    assert result.sections[0]["text"] == "# Alpha\nAlpha body"


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
    assert result.text == (
        "# Alpha\nAlpha body\n\n# Beta\nBeta body"
    )


def test_clipping_contract():
    long_text = "# Long\n" + ("x" * 100 + "\n") * 20

    result = select_sections(long_text, ["long"], 10)

    assert result.truncated is True
    assert len(result.text) <= 40