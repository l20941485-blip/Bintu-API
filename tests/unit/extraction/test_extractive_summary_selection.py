from bintu_api.extraction.summarizer import build_extractive_summary

MARKDOWN = (
    "# Guide\n\n"
    "Bintu extracts clean Markdown and returns source offsets.\n\n"
    "The extraction service supports deterministic caching.\n\n"
    "## Usage\n\n"
    "Call the extraction endpoint with a public URL."
)


def test_selection_diagnostics_describe_leading_selection():
    summary = build_extractive_summary(
        MARKDOWN,
        mode="leading",
        sentence_count=2,
    )

    diagnostics = summary.diagnostics

    assert diagnostics.candidate_count >= 2
    assert diagnostics.selected_indices == (0, 1)
    assert diagnostics.scores == (1.0, 1.0)
    assert diagnostics.redundancy_threshold == 0.85
    assert len(diagnostics.heading_paths) == 2


def test_selection_diagnostics_describe_key_sentence_selection():
    summary = build_extractive_summary(
        MARKDOWN,
        mode="key_sentences",
        sentence_count=2,
    )

    diagnostics = summary.diagnostics

    assert diagnostics.candidate_count >= 2
    assert len(diagnostics.selected_indices) == 2
    assert len(diagnostics.scores) == 2
    assert len(diagnostics.heading_paths) == 2
    assert diagnostics.redundancy_threshold == 0.85
    assert all(score > 0.0 for score in diagnostics.scores)


def test_selection_diagnostics_are_deterministic():
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

    assert first.diagnostics == second.diagnostics


def test_empty_markdown_has_empty_selection_diagnostics():
    summary = build_extractive_summary(
        "",
        mode="leading",
        sentence_count=2,
    )

    assert summary.diagnostics.candidate_count == 0
    assert summary.diagnostics.selected_indices == ()
    assert summary.diagnostics.scores == ()
    assert summary.diagnostics.heading_paths == ()


BOILERPLATE_AND_REDUNDANT_MARKDOWN = (
    "# Reference Guide\n\n"
    "From Wikipedia, the free encyclopedia.\n\n"
    "IronPython Jython MicroPython Nuitka Numba Parrot\n\n"
    "Bintu extracts clean Markdown from HTML pages and returns character offsets.\n\n"
    "Bintu extracts clean Markdown from HTML pages with character offsets.\n\n"
    "## Caching and Observability\n\n"
    "Content-addressed caching and stage traces keep repeated extractions fast and auditable."
)


def test_key_sentences_diverges_from_leading_on_boilerplate_and_duplicates():
    leading = build_extractive_summary(
        BOILERPLATE_AND_REDUNDANT_MARKDOWN,
        mode="leading",
        sentence_count=2,
    )
    key = build_extractive_summary(
        BOILERPLATE_AND_REDUNDANT_MARKDOWN,
        mode="key_sentences",
        sentence_count=2,
    )

    assert "IronPython Jython MicroPython" not in leading.text
    assert "IronPython Jython MicroPython" not in key.text
    assert key.text != leading.text
    assert key.diagnostics.selected_indices != leading.diagnostics.selected_indices
    assert any("Caching and Observability" in path for path in key.diagnostics.heading_paths)
