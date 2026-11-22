from bintu_api.extraction.summarizer import build_extractive_summary
from bintu_api.extraction.summary_quality import evaluate_extractive_summary


def test_quality_report_measures_faithful_diverse_summary():
    markdown = (
        "# Guide\n\n"
        "Bintu extracts clean Markdown and preserves source context.\n\n"
        "Bintu extracts clean Markdown and preserves source context.\n\n"
        "The extraction service supports deterministic caching.\n\n"
        "It also returns source offsets for selected sentences."
    )

    summary = build_extractive_summary(
        markdown,
        mode="key_sentences",
        sentence_count=2,
    )
    report = evaluate_extractive_summary(markdown, summary)

    assert report["faithful"] is True
    assert report["sentence_count"] == 2
    assert report["source_order_preserved"] is True
    assert report["coverage"] > 0.0
    assert report["redundancy"] < 1.0
    assert report["coherence"] == 1.0


def test_quality_report_detects_unfaithful_summary():
    markdown = "Bintu extracts clean Markdown and preserves source context."
    summary = build_extractive_summary(
        markdown,
        mode="leading",
        sentence_count=1,
    )

    report = evaluate_extractive_summary(
        markdown,
        summary,
        summary_texts=["Bintu invented a fact."],
    )

    assert report["faithful"] is False


def test_quality_report_includes_review_fields():
    markdown = "Bintu extracts clean Markdown and preserves source context."
    summary = build_extractive_summary(
        markdown,
        mode="leading",
        sentence_count=1,
    )

    report = evaluate_extractive_summary(markdown, summary)

    assert report["review_status"] == "unreviewed"
    assert report["reviewer"] is None
    assert report["notes"] == ""


def test_quality_report_validates_exact_source_grounding():
    markdown = (
        "# Guide\n\n"
        "Bintu extracts clean Markdown for retrieval.\n\n"
        "It preserves headings and source context."
    )

    summary = build_extractive_summary(
        markdown,
        mode="key_sentences",
        sentence_count=2,
    )
    report = evaluate_extractive_summary(markdown, summary)

    assert report["grounding_valid"] is True
    assert report["provenance_valid"] is True
    assert report["faithful"] is True

    for sentence in summary.sentences:
        assert markdown[sentence.char_start:sentence.char_end] == sentence.text


def test_quality_report_detects_invalid_source_span():
    markdown = "Bintu extracts clean Markdown and preserves source context."
    summary = build_extractive_summary(
        markdown,
        mode="leading",
        sentence_count=1,
    )

    altered = summary.sentences[0]
    object.__setattr__(altered, "char_end", altered.char_end - 1)

    report = evaluate_extractive_summary(markdown, summary)

    assert report["grounding_valid"] is False
    assert report["faithful"] is False


def test_quality_report_detects_invalid_provenance():
    markdown = "Bintu extracts clean Markdown and preserves source context."
    summary = build_extractive_summary(
        markdown,
        mode="leading",
        sentence_count=1,
    )

    object.__setattr__(summary, "source_fingerprint", "invalid")

    report = evaluate_extractive_summary(markdown, summary)

    assert report["provenance_valid"] is False
    assert report["faithful"] is False


def test_quality_report_measures_summary_precision_and_tokens():
    markdown = (
        "Bintu extracts clean Markdown and preserves source context.\n\n"
        "The extraction service supports deterministic caching."
    )

    summary = build_extractive_summary(
        markdown,
        mode="key_sentences",
        sentence_count=2,
    )
    report = evaluate_extractive_summary(markdown, summary)

    assert report["summary_precision"] == 1.0
    assert report["summary_token_count"] > 0
    assert report["coverage"] > 0.0


def test_quality_report_handles_empty_summary_tokens():
    markdown = "Bintu extracts clean Markdown."
    summary = build_extractive_summary(
        markdown,
        mode="leading",
        sentence_count=1,
    )

    report = evaluate_extractive_summary(
        markdown,
        summary,
        summary_texts=[""],
    )

    assert report["summary_precision"] == 1.0
    assert report["summary_token_count"] == 0


def test_quality_report_includes_selection_diagnostics():
    markdown = (
        "# Guide\n\n"
        "Bintu extracts clean Markdown and returns source offsets.\n\n"
        "The extraction service supports deterministic caching.\n\n"
        "## Usage\n\n"
        "Call the extraction endpoint with a public URL."
    )

    summary = build_extractive_summary(
        markdown,
        mode="key_sentences",
        sentence_count=2,
    )
    report = evaluate_extractive_summary(markdown, summary)

    assert report["candidate_count"] == summary.diagnostics.candidate_count
    assert report["selected_count"] == 2
    assert 0.0 < report["selection_ratio"] <= 1.0
    assert report["mean_selected_score"] > 0.0
    assert 0.0 <= report["selection_diversity"] <= 1.0


def test_quality_report_handles_empty_selection_diagnostics():
    summary = build_extractive_summary(
        "",
        mode="leading",
        sentence_count=2,
    )
    report = evaluate_extractive_summary("", summary)

    assert report["candidate_count"] == 0
    assert report["selected_count"] == 0
    assert report["selection_ratio"] == 0.0
    assert report["mean_selected_score"] == 0.0
    assert report["selection_diversity"] == 1.0
