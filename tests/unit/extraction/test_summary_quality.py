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
