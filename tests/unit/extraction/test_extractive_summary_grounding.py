from bintu_api.extraction.summarizer import (
    EXTRACTIVE_SUMMARY_ALGORITHM_VERSION,
    build_extractive_summary,
)

MARKDOWN = (
    "# Guide\n\n"
    "Bintu extracts clean Markdown for retrieval.\n\n"
    "It preserves headings and source context."
)


def test_selected_sentences_are_exact_source_slices():
    summary = build_extractive_summary(
        MARKDOWN,
        mode="key_sentences",
        sentence_count=2,
    )

    assert summary.sentences

    for sentence in summary.sentences:
        assert MARKDOWN[sentence.char_start:sentence.char_end] == sentence.text


def test_summary_records_internal_provenance():
    summary = build_extractive_summary(
        MARKDOWN,
        mode="key_sentences",
        sentence_count=2,
    )

    assert summary.algorithm_version == EXTRACTIVE_SUMMARY_ALGORITHM_VERSION
    assert summary.source_fingerprint


def test_summary_is_deterministic():
    first = build_extractive_summary(
        MARKDOWN,
        mode="key_sentences",
        sentence_count=2,
    )
    second = build_extractive_summary(
        MARKDOWN,
        mode="key_sentences",
        sentence_count=2,
    )

    assert first == second


def test_leading_mode_preserves_exact_source_spans():
    summary = build_extractive_summary(
        MARKDOWN,
        mode="leading",
        sentence_count=2,
    )

    for sentence in summary.sentences:
        assert MARKDOWN[sentence.char_start:sentence.char_end] == sentence.text
