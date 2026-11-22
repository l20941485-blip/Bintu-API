"""Sentence-aware, token-budgeted summarization utilities."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from bintu_api.extraction.chunker import (
    _HEADING_LINE,
    count_tokens,
    sentence_pieces,
)


def _units(text: str) -> list[str]:
    """Lines, except that a fenced block is one atomic unit."""
    units: list[str] = []
    buffer: list[str] | None = None
    for line in text.split("\n"):
        if buffer is not None:
            buffer.append(line)
            if line.startswith("```"):
                units.append("\n".join(buffer))
                buffer = None
        elif line.startswith("```"):
            buffer = [line]
        else:
            units.append(line)
    if buffer:
        units.append("\n".join(buffer) + "\n```")
    return [unit for unit in units if unit.strip()]


def _hard_cut(text: str, max_tokens: int) -> str:
    budget = max_tokens * 4 - 1
    if budget <= 0:
        return ""
    cut = text[:budget]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip() + "\u2026"


def summarize_text(text: str, max_tokens: int) -> tuple[str, bool]:
    """Return (summary, truncated) with count_tokens(summary) <= max_tokens.

    Keeps the document's own line structure (headings stay on their own line),
    includes whole lines while they fit, then whole sentences of the first
    line that does not fit. Never ends on a heading and never leaves a fence open.
    """
    if count_tokens(text) <= max_tokens:
        return text, False

    selected: list[str] = []
    for unit in _units(text):
        if count_tokens("\n".join(selected + [unit])) <= max_tokens:
            selected.append(unit)
            continue
        if not unit.startswith("```") and not _HEADING_LINE.match(unit):
            partial: list[str] = []
            for sentence in sentence_pieces(unit):
                candidate = "\n".join(selected + [" ".join(partial + [sentence])])
                if count_tokens(candidate) <= max_tokens:
                    partial.append(sentence)
                else:
                    break
            if partial:
                selected.append(" ".join(partial))
        break

    while selected and _HEADING_LINE.match(selected[-1]):
        selected.pop()  # never end on a heading with nothing under it

    result = "\n".join(selected)
    if not result.strip():
        result = _hard_cut(text, max_tokens)
    return result, True


@dataclass(frozen=True)
class SummarySentence:
    text: str
    heading_path: tuple[str, ...]
    char_start: int
    char_end: int
    score: float


@dataclass(frozen=True)
class ExtractiveSummary:
    mode: Literal["leading", "key_sentences"]
    text: str
    sentences: tuple[SummarySentence, ...]
    requested_sentence_count: int
    returned_sentence_count: int
    truncated: bool


_EXTRACTIVE_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_FENCE_RE = re.compile(r"^```")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


def _is_inside_fence(lines: list[str], index: int) -> bool:
    fence_count = sum(
        1
        for line in lines[: index + 1]
        if _FENCE_RE.match(line.strip())
    )
    return fence_count % 2 == 1


def _active_heading(lines: list[str], index: int) -> tuple[str, ...]:
    path: list[str] = []

    for line in lines[:index]:
        match = _EXTRACTIVE_HEADING_RE.match(line.strip())
        if match is None:
            continue

        level = len(match.group(1))
        path = path[: level - 1]
        path.append(match.group(2).strip())

    return tuple(path)


def _split_extractive_sentences(
    markdown: str,
) -> list[tuple[str, int, int, tuple[str, ...]]]:
    lines = markdown.split("\n")
    candidates: list[tuple[str, int, int, tuple[str, ...]]] = []

    for line_index, line in enumerate(lines):
        stripped = line.strip()

        if not stripped or _EXTRACTIVE_HEADING_RE.match(stripped):
            continue

        if _is_inside_fence(lines, line_index):
            continue

        heading_path = _active_heading(lines, line_index)
        cursor = 0

        for sentence in _SENTENCE_RE.split(stripped):
            start = markdown.find(sentence, cursor)
            if start == -1:
                continue

            end = start + len(sentence)
            candidates.append(
                (
                    sentence.strip(),
                    start,
                    end,
                    heading_path,
                )
            )
            cursor = end

    return candidates


def _is_eligible_summary_sentence(sentence: str) -> bool:
    return len(sentence) >= 30


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


def _content_tokens(sentence: str) -> frozenset[str]:
    tokens = re.findall(r"[\w]+", sentence.lower())
    return frozenset(token for token in tokens if token not in _STOPWORDS)


def _jaccard_similarity(
    left: frozenset[str],
    right: frozenset[str],
) -> float:
    if not left or not right:
        return 0.0

    intersection = len(left & right)
    union = len(left | right)
    return intersection / union


def _salience_score(
    sentence: str,
    heading_path: tuple[str, ...],
    position: int,
    candidate_count: int,
) -> float:
    tokens = _content_tokens(sentence)

    length_score = min(1.0, len(tokens) / 18.0)
    position_score = 1.0 - (position / max(1, candidate_count))
    heading_score = min(1.0, len(heading_path) / 3.0)

    return 0.55 * length_score + 0.30 * position_score + 0.15 * heading_score


def _select_key_sentences(
    candidates: list[tuple[str, int, int, tuple[str, ...]]],
    sentence_count: int,
) -> list[tuple[str, int, int, tuple[str, ...]]]:
    """Select diverse, salient sentences with deterministic MMR."""
    scored = [
        (
            _salience_score(
                text,
                heading_path,
                index,
                len(candidates),
            ),
            index,
            text,
            start,
            end,
            heading_path,
            _content_tokens(text),
        )
        for index, (text, start, end, heading_path) in enumerate(candidates)
    ]

    selected: list[tuple[int, tuple[str, int, int, tuple[str, ...]], frozenset[str]]] = []
    remaining = list(scored)

    while remaining and len(selected) < sentence_count:
        selected_tokens = [item[2] for item in selected]

        if not selected_tokens:
            available = remaining
        else:
            available = [
                item
                for item in remaining
                if all(
                    _jaccard_similarity(item[6], token) < 0.85
                    for token in selected_tokens
                )
            ] or remaining

        if not selected_tokens:
            best = min(
                available,
                key=lambda item: (-item[0], item[1]),
            )
        else:
            def redundancy_penalty(
                item,
                _selected_tokens=selected_tokens,
            ):
                maximum = max(
                    _jaccard_similarity(item[6], token)
                    for token in _selected_tokens
                )
                return -(item[0] - 0.65 * maximum)

            best = min(
                available,
                key=lambda item: (redundancy_penalty(item), item[1]),
            )

        selected.append((best[1], (best[2], best[3], best[4], best[5]), best[6]))
        remaining.remove(best)

    return [
        item[1]
        for item in sorted(selected, key=lambda item: item[0])
    ]


def build_extractive_summary(
    markdown: str,
    *,
    mode: Literal["leading", "key_sentences"],
    sentence_count: int,
) -> ExtractiveSummary:
    """Build a deterministic, source-grounded extractive summary."""
    if sentence_count < 1:
        raise ValueError("sentence_count must be at least 1")

    candidates = list(
        dict.fromkeys(
            (text, start, end, heading_path)
            for text, start, end, heading_path in _split_extractive_sentences(markdown)
            if _is_eligible_summary_sentence(text)
        )
    )

    if not candidates:
        return ExtractiveSummary(
            mode=mode,
            text="",
            sentences=(),
            requested_sentence_count=sentence_count,
            returned_sentence_count=0,
            truncated=False,
        )

    if mode == "leading":
        selected = candidates[:sentence_count]
    else:
        selected = _select_key_sentences(candidates, sentence_count)

    sentences = tuple(
        SummarySentence(
            text=text,
            heading_path=heading_path,
            char_start=start,
            char_end=end,
            score=1.0 if mode == "leading" else _salience_score(
                text,
                heading_path,
                index,
                len(candidates),
            ),
        )
        for index, (text, start, end, heading_path) in enumerate(candidates)
        if (text, start, end, heading_path) in selected
    )

    return ExtractiveSummary(
        mode=mode,
        text=" ".join(sentence.text for sentence in sentences),
        sentences=sentences,
        requested_sentence_count=sentence_count,
        returned_sentence_count=len(sentences),
        truncated=len(sentences) < sentence_count,
    )
