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


def build_extractive_summary(
    markdown: str,
    *,
    mode: Literal["leading", "key_sentences"],
    sentence_count: int,
) -> ExtractiveSummary:
    """Build a deterministic, source-grounded extractive summary."""
    if sentence_count < 1:
        raise ValueError("sentence_count must be at least 1")

    candidates = [
        (text, start, end, heading_path)
        for text, start, end, heading_path in _split_extractive_sentences(markdown)
        if _is_eligible_summary_sentence(text)
    ]

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
        ranked = sorted(
            enumerate(candidates),
            key=lambda item: (-len(item[1][0]), item[0]),
        )[:sentence_count]
        selected = [
            candidates[index]
            for index, _ in sorted(ranked, key=lambda item: item[0])
        ]

    sentences = tuple(
        SummarySentence(
            text=text,
            heading_path=heading_path,
            char_start=start,
            char_end=end,
            score=1.0 if mode == "leading" else min(1.0, len(text) / 240),
        )
        for text, start, end, heading_path in selected
    )

    return ExtractiveSummary(
        mode=mode,
        text=" ".join(sentence.text for sentence in sentences),
        sentences=sentences,
        requested_sentence_count=sentence_count,
        returned_sentence_count=len(sentences),
        truncated=len(sentences) < sentence_count,
    )
