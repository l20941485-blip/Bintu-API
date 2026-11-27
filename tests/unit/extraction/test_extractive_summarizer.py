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
        "Bintu extracts clean Markdown for retrieval.\n\n"
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


def test_key_sentences_avoid_near_duplicate_sentences():
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

    texts = [sentence.text for sentence in summary.sentences]

    assert len(texts) == 2
    assert len(set(texts)) == 2
    assert (
        "Bintu extracts clean Markdown and preserves source context."
        in texts
    )
    assert (
        "The extraction service supports deterministic caching."
        in texts
        or "It also returns source offsets for selected sentences."
        in texts
    )


def test_key_sentences_prefers_informative_sentences():
    markdown = (
        "# Guide\n\n"
        "This page explains Bintu.\n\n"
        "Bintu extracts clean Markdown and returns source offsets.\n\n"
        "The extraction service supports deterministic caching."
    )

    summary = build_extractive_summary(
        markdown,
        mode="key_sentences",
        sentence_count=2,
    )

    texts = [sentence.text for sentence in summary.sentences]

    assert (
        "Bintu extracts clean Markdown and returns source offsets."
        in texts
    )
    assert (
        "The extraction service supports deterministic caching."
        in texts
    )


def test_key_sentences_supports_cjk_sentence_boundaries():
    markdown = (
        "# 指南\n\n"
        "这是第一个完整的句子，说明提取服务如何工作。\n"
        "这是第二个完整的句子，解释来源偏移量。\n\n"
        "第三个句子介绍确定性缓存。"
    )

    summary = build_extractive_summary(
        markdown,
        mode="leading",
        sentence_count=3,
    )

    texts = [sentence.text for sentence in summary.sentences]

    assert texts == [
        "这是第一个完整的句子，说明提取服务如何工作。",
        "这是第二个完整的句子，解释来源偏移量。",
        "第三个句子介绍确定性缓存。",
    ]
    assert summary.sentences[0].char_start < summary.sentences[1].char_start
    assert summary.sentences[1].char_start < summary.sentences[2].char_start


def test_key_sentences_supports_unicode_uppercase_boundaries():
    markdown = (
        "# Guide\n\n"
        "Ceci est la première phrase de l’exemple.\n"
        "Également, cette phrase doit être séparée correctement.\n\n"
        "Cette dernière phrase explique les décalages source."
    )

    summary = build_extractive_summary(
        markdown,
        mode="leading",
        sentence_count=3,
    )

    texts = [sentence.text for sentence in summary.sentences]

    assert texts == [
        "Ceci est la première phrase de l’exemple.",
        "Également, cette phrase doit être séparée correctement.",
        "Cette dernière phrase explique les décalages source.",
    ]





def test_key_sentences_deduplicates_redundant_statements_in_order() -> None:
    from bintu_api.extraction.summarizer import build_extractive_summary

    markdown = (
        "## Overview\n\n"
        "Worker threads isolate blocking database calls from the asyncio event loop. "
        "Worker threads isolate blocking database calls from the asyncio event loop.\n\n"
        "## Timeouts\n\n"
        "Explicit two-second timeouts prevent stalled requests from exhausting connection pools. "
        "Explicit two-second timeouts prevent stalled requests from exhausting connection pools.\n\n"
        "## Observability\n\n"
        "Structured timeout metrics record upstream latency across retrieval endpoints."
    )
    summary = build_extractive_summary(
        markdown,
        mode="key_sentences",
        sentence_count=3,
    )

    sentence_texts = [sentence.text for sentence in summary.sentences]
    assert summary.mode == "key_sentences"
    assert len(sentence_texts) <= 3
    assert len(sentence_texts) == len(set(sentence_texts))
    assert any("Worker threads isolate blocking database calls" in s for s in sentence_texts)
    assert any("Explicit two-second timeouts prevent stalled requests" in s for s in sentence_texts)

def test_extractive_summary_preserves_version_numbers_and_abbreviations() -> None:
    markdown = (
        "## Release Notes\n\n"
        "Version 1.4.0 improves extraction speed across documents. "
        "It supports e.g. HTML and Markdown inputs reliably. "
        "2026 benchmarks confirm steady throughput across retrieval runs."
    )

    summary = build_extractive_summary(
        markdown,
        mode="leading",
        sentence_count=3,
    )

    texts = [sentence.text for sentence in summary.sentences]
    assert texts[0] == "Version 1.4.0 improves extraction speed across documents."
    assert texts[1].strip() == "It supports e.g. HTML and Markdown inputs reliably."
    assert texts[2].strip() == "2026 benchmarks confirm steady throughput across retrieval runs."
