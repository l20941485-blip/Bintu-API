import pytest

from bintu_api.extraction.summarizer import build_extractive_summary
from bintu_api.extraction.summary_quality import evaluate_extractive_summary

LONG_DOCUMENT = """# Product guide

Bintu extracts clean Markdown from web pages and preserves source context.

The extraction service removes boilerplate while retaining meaningful content.

## Usage

Call the extraction endpoint with a public URL and an API key.

The response includes source offsets for every selected summary sentence.

## Caching

Deterministic caching reduces repeated extraction work.

Cached results preserve the same extraction behavior across requests.

## Limitations

JavaScript-rendered content may require the rendering option.

The service does not invent content that is absent from the source page.
"""

SHORT_DOCUMENT = "# Guide\n\nOnly one useful sentence exists here."

REPEATED_BOILERPLATE = """# Guide

Bintu extracts clean Markdown and preserves source context.

Bintu extracts clean Markdown and preserves source context.

Bintu extracts clean Markdown and preserves source context.

The extraction service supports deterministic caching.
"""

MIXED_SCRIPT_DOCUMENT = """# Guide

Bintu extracts clean Markdown and preserves source context.

Ceci est la première phrase de l’exemple.

这是第二个完整的句子，解释来源偏移量。

The extraction service supports deterministic caching.
"""


@pytest.mark.parametrize(
    ("markdown", "expected_count"),
    [
        (LONG_DOCUMENT, 3),
        (SHORT_DOCUMENT, 1),
        (REPEATED_BOILERPLATE, 2),
        (MIXED_SCRIPT_DOCUMENT, 2),
    ],
)
def test_realistic_documents_remain_source_grounded(
    markdown: str,
    expected_count: int,
):
    summary = build_extractive_summary(
        markdown,
        mode="key_sentences",
        sentence_count=expected_count,
    )
    report = evaluate_extractive_summary(markdown, summary)

    assert summary.returned_sentence_count == expected_count
    assert report["faithful"] is True
    assert report["source_order_preserved"] is True
    assert report["coverage"] > 0.0
    assert report["coherence"] == 1.0


def test_long_document_selects_distinct_sections():
    summary = build_extractive_summary(
        LONG_DOCUMENT,
        mode="key_sentences",
        sentence_count=3,
    )

    heading_paths = [sentence.heading_path for sentence in summary.sentences]

    assert len(set(heading_paths)) >= 2


def test_repeated_boilerplate_is_not_duplicated():
    summary = build_extractive_summary(
        REPEATED_BOILERPLATE,
        mode="key_sentences",
        sentence_count=2,
    )

    texts = [sentence.text for sentence in summary.sentences]

    assert len(texts) == len(set(texts))
