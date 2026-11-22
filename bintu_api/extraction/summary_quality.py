"""Deterministic, offline evaluation for extractive summaries.

The harness measures properties that can be verified directly against the
source document. It does not use a language model or network service.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

from bintu_api.extraction.summarizer import (
    EXTRACTIVE_SUMMARY_ALGORITHM_VERSION,
    ExtractiveSummary,
)

_WORD_RE = re.compile(r"[\w]+", re.UNICODE)

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "their",
        "this",
        "to",
        "was",
        "were",
        "with",
    }
)


def _source_fingerprint(markdown: str) -> str:
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def _content_tokens(text: str) -> set[str]:
    return {
        token
        for token in _WORD_RE.findall(text.lower())
        if token not in _STOPWORDS
    }


def _jaccard_similarity(
    left: set[str],
    right: set[str],
) -> float:
    if not left or not right:
        return 0.0

    return len(left & right) / len(left | right)


def evaluate_extractive_summary(
    markdown: str,
    summary: ExtractiveSummary,
    *,
    summary_texts: Iterable[str] | None = None,
) -> dict[str, float | int | bool]:
    """Return deterministic quality measures for an extractive summary.

    ``summary_texts`` permits evaluation of a rendered summary that may have
    been altered after extraction. When omitted, the summary's own sentence
    texts are evaluated.
    """
    texts = (
        list(summary_texts)
        if summary_texts is not None
        else [sentence.text for sentence in summary.sentences]
    )

    source_tokens = _content_tokens(markdown)
    summary_tokens = _content_tokens(" ".join(texts))

    coverage = (
        len(source_tokens & summary_tokens) / len(source_tokens)
        if source_tokens
        else 1.0
    )

    grounding_valid = all(
        markdown[sentence.char_start:sentence.char_end] == sentence.text
        for sentence in summary.sentences
    )
    provenance_valid = (
        summary.source_fingerprint == _source_fingerprint(markdown)
        and summary.algorithm_version == EXTRACTIVE_SUMMARY_ALGORITHM_VERSION
    )

    faithful = (
        grounding_valid
        and provenance_valid
        and all(text in markdown for text in texts)
    )

    source_order_preserved = all(
        summary.sentences[index].char_start
        < summary.sentences[index + 1].char_start
        for index in range(len(summary.sentences) - 1)
    )

    token_sets = [_content_tokens(text) for text in texts]
    redundancy = 0.0
    for left_index, left in enumerate(token_sets):
        for right in token_sets[left_index + 1 :]:
            redundancy = max(
                redundancy,
                _jaccard_similarity(left, right),
            )

    positions = [sentence.char_start for sentence in summary.sentences]
    coherence = (
        1.0
        if all(
            positions[index] < positions[index + 1]
            for index in range(len(positions) - 1)
        )
        else 0.0
    )

    return {
        "faithful": faithful,
        "grounding_valid": grounding_valid,
        "provenance_valid": provenance_valid,
        "coverage": coverage,
        "redundancy": redundancy,
        "coherence": coherence,
        "source_order_preserved": source_order_preserved,
        "sentence_count": len(texts),
        "review_status": "unreviewed",
        "reviewer": None,
        "notes": "",
    }
