from bintu_api.extraction.summarizer import build_extractive_summary


def test_leading_mode_returns_first_eligible_sentences_in_order():
    markdown = (
        "# Guide\n\n"
        "Bintu extracts clean Markdown for retrieval.\n\n"
        "It preserves headings and source context.\n\n"
        "## Usage\n\n"
        "Call the extraction endpoint with a public URL."
    )

    summary = build_extractive_summary(
        markdown,
        mode="leading",
        sentence_count=2,
    )

    assert summary.mode == "leading"
    assert summary.text == (
        "Bintu extracts clean Markdown for retrieval. "
        "It preserves headings and source context."
    )
    assert [sentence.text for sentence in summary.sentences] == [
        "Bintu extracts clean Markdown for retrieval.",
        "It preserves headings and source context.",
    ]


def test_key_sentences_preserves_source_order():
    markdown = (
        "# Guide\n\n"
        "Bintu extracts clean Markdown for retrieval.\n\n"
        "It preserves headings and source context.\n\n"
        "## Usage\n\n"
        "Call the extraction endpoint with a public URL."
    )

    summary = build_extractive_summary(
        markdown,
        mode="key_sentences",
        sentence_count=2,
    )

    assert summary.mode == "key_sentences"
    assert len(summary.sentences) == 2
    assert summary.sentences[0].char_start < summary.sentences[1].char_start
    assert all(sentence.text in markdown for sentence in summary.sentences)


def test_headings_are_not_summary_sentences():
    markdown = (
        "# Guide\n\n"
        "Meaningful body content with enough information.\n\n"
        "## References\n\n"
        "[1] Example reference."
    )

    summary = build_extractive_summary(
        markdown,
        mode="leading",
        sentence_count=1,
    )

    assert summary.sentences[0].text == (
        "Meaningful body content with enough information."
    )


def test_short_document_reports_truncation():
    markdown = "# Guide\n\nOnly one useful sentence exists here."

    summary = build_extractive_summary(
        markdown,
        mode="leading",
        sentence_count=3,
    )

    assert summary.returned_sentence_count == 1
    assert summary.truncated is True


def test_empty_markdown_returns_empty_summary():
    summary = build_extractive_summary(
        "",
        mode="leading",
        sentence_count=3,
    )

    assert summary.text == ""
    assert summary.sentences == ()
    assert summary.truncated is False
