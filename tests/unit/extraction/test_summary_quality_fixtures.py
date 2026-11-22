import pytest

from bintu_api.extraction.summarizer import build_extractive_summary
from bintu_api.extraction.summary_quality import evaluate_extractive_summary

ENGLISH_MARKDOWN = """# Guide

Bintu extracts clean Markdown and preserves source context.

The extraction service supports deterministic caching.

It also returns source offsets for selected sentences.
"""

FRENCH_MARKDOWN = """# Guide

Bintu extrait du Markdown propre et préserve le contexte source.

Le service d’extraction prend en charge la mise en cache déterministe.

Il renvoie également les décalages source des phrases sélectionnées.
"""

CHINESE_MARKDOWN = """# 指南

Bintu 提取干净的 Markdown 并保留来源上下文。

提取服务支持确定性缓存。

它还会返回所选句子的来源偏移量。
"""

CODE_MARKDOWN = """# Guide

Bintu extracts clean Markdown and preserves source context.

```python
print("This implementation detail must not become a summary sentence.")
```

The extraction service supports deterministic caching.
"""


@pytest.mark.parametrize(
    ("markdown", "minimum_coverage"),
    [
        (ENGLISH_MARKDOWN, 0.5),
        (FRENCH_MARKDOWN, 0.5),
        (CHINESE_MARKDOWN, 0.5),
        (CODE_MARKDOWN, 0.5),
    ],
)
def test_key_sentences_meet_baseline_quality(
    markdown: str,
    minimum_coverage: float,
):
    summary = build_extractive_summary(
        markdown,
        mode="key_sentences",
        sentence_count=2,
    )
    report = evaluate_extractive_summary(markdown, summary)

    assert summary.returned_sentence_count == 2
    assert report["faithful"] is True
    assert report["source_order_preserved"] is True
    assert report["coverage"] >= minimum_coverage
    assert report["redundancy"] < 0.85
    assert report["coherence"] == 1.0


def test_code_heavy_document_excludes_fenced_content():
    summary = build_extractive_summary(
        CODE_MARKDOWN,
        mode="key_sentences",
        sentence_count=2,
    )

    assert all(
        "implementation detail" not in sentence.text.lower()
        for sentence in summary.sentences
    )
