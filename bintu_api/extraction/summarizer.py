"""Sentence-aware, token-budgeted summarization utilities."""

from __future__ import annotations

import hashlib
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
class SelectionDiagnostics:
    candidate_count: int
    selected_indices: tuple[int, ...]
    scores: tuple[float, ...]
    heading_paths: tuple[tuple[str, ...], ...]
    redundancy_threshold: float


@dataclass(frozen=True)
class ExtractiveSummary:
    mode: Literal["leading", "key_sentences"]
    text: str
    sentences: tuple[SummarySentence, ...]
    requested_sentence_count: int
    returned_sentence_count: int
    truncated: bool
    algorithm_version: str
    source_fingerprint: str
    diagnostics: SelectionDiagnostics


EXTRACTIVE_SUMMARY_ALGORITHM_VERSION = "v1-grounded-mmr"


def _source_fingerprint(markdown: str) -> str:
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


_EXTRACTIVE_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_FENCE_RE = re.compile(r"^```")
_LATIN_SENTENCE_BOUNDARY_RE = re.compile(
    r"(?<=[.!?…])"
    r"(?=[\"')\]]*\s+(?=[^\s])|$)"
)

_CJK_SENTENCE_BOUNDARY_RE = re.compile(
    r"(?<=[。！？])"
    r"(?=[\"')\]]*|$)"
)

_SENTENCE_BOUNDARY_RE = re.compile(
    rf"(?:{_LATIN_SENTENCE_BOUNDARY_RE.pattern}|{_CJK_SENTENCE_BOUNDARY_RE.pattern})"
)

_ABBREVIATION_SUFFIX_RE = re.compile(
    r"(?:\b(?:e\.g|i\.e|etc|vs|dr|mr|mrs|ms|prof|fig|no|vol|pp|st)\.|(?:\b[a-zA-Z]\.){2,})$",
    re.IGNORECASE,
)
_DECIMAL_OR_VERSION_RE = re.compile(r"(?:\d+\.\d+|\d+\.)$")
_NEXT_TOKEN_LOWER_RE = re.compile(r"^[\"')\]]*\s+[a-z0-9]")


_TRAILING_CLOSERS = "\"')]}”’）】"


def _split_line_sentences(stripped: str) -> list[str]:
    raw_parts = _SENTENCE_BOUNDARY_RE.split(stripped)
    if len(raw_parts) <= 1:
        return [part for part in raw_parts if part.strip()]

    merged: list[str] = []
    for part in raw_parts:
        if not part:
            continue
        if not merged:
            merged.append(part)
            continue

        prev = merged[-1]
        prev_trimmed = prev.rstrip(_TRAILING_CLOSERS)
        has_period = prev_trimmed.endswith(".")
        is_decimal_or_version = bool(_DECIMAL_OR_VERSION_RE.search(prev_trimmed))
        is_abbreviation = bool(_ABBREVIATION_SUFFIX_RE.search(prev_trimmed))
        starts_lowercase_or_digit = bool(_NEXT_TOKEN_LOWER_RE.match(part))

        if has_period and (is_decimal_or_version or is_abbreviation or starts_lowercase_or_digit):
            merged[-1] = prev + part
        else:
            merged.append(part)

    return [item for item in merged if item.strip()]


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

        for sentence in _split_line_sentences(stripped):
            start = markdown.find(sentence, cursor)
            if start == -1:
                continue

            end = start + len(sentence)
            exact_sentence = markdown[start:end]
            candidates.append(
                (
                    exact_sentence,
                    start,
                    end,
                    heading_path,
                )
            )
            cursor = end

    return candidates


_CJK_CHARACTER_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")


def _is_eligible_summary_sentence(sentence: str) -> bool:
    if len(sentence) >= 30:
        return True

    # CJK sentences convey substantially more information per character than
    # whitespace-delimited scripts, so use a lower character threshold.
    return len(sentence) >= 12 and bool(_CJK_CHARACTER_RE.search(sentence))


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


_GENERIC_OPENER_PREFIXES = (
    "in this article",
    "in this guide",
    "in this post",
    "click here",
    "learn more",
    "read more",
    "subscribe to",
)


def _has_generic_opener(sentence: str) -> bool:
    normalized = " ".join(sentence.strip().lower().split())
    return any(normalized.startswith(prefix) for prefix in _GENERIC_OPENER_PREFIXES)


def _salience_score(
    sentence: str,
    heading_path: tuple[str, ...],
    position: int,
    candidate_count: int,
) -> float:
    tokens = _content_tokens(sentence)
    heading_tokens = _content_tokens(" ".join(heading_path))

    length_score = min(1.0, len(tokens) / 18.0)
    position_score = 1.0 - (position / max(1, candidate_count))

    depth_score = min(1.0, len(heading_path) / 3.0)
    if heading_tokens and tokens:
        overlap_ratio = len(tokens & heading_tokens) / len(heading_tokens)
        heading_score = 0.5 * depth_score + 0.5 * min(1.0, overlap_ratio)
    else:
        heading_score = depth_score

    opener_penalty = 0.12 if _has_generic_opener(sentence) else 0.0
    score = (
        0.55 * length_score
        + 0.30 * position_score
        + 0.15 * heading_score
        - opener_penalty
    )
    return max(0.0, score)


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
        selected_token_sets = [item[2] for item in selected]

        if not selected_token_sets:
            available = remaining
        else:
            available = [
                item
                for item in remaining
                if all(
                    _jaccard_similarity(item[6], token_set) < 0.85
                    for token_set in selected_token_sets
                )
            ] or remaining

        if not selected_token_sets:
            best = min(
                available,
                key=lambda item: (-item[0], item[1]),
            )
        else:
            def redundancy_penalty(
                item,
                _selected_token_sets=selected_token_sets,
            ):
                maximum = max(
                    _jaccard_similarity(item[6], token_set)
                    for token_set in _selected_token_sets
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
            algorithm_version=EXTRACTIVE_SUMMARY_ALGORITHM_VERSION,
            source_fingerprint=_source_fingerprint(markdown),
            diagnostics=SelectionDiagnostics(
                candidate_count=0,
                selected_indices=(),
                scores=(),
                heading_paths=(),
                redundancy_threshold=0.85,
            ),
        )

    if mode == "leading":
        selected = candidates[:sentence_count]
    else:
        selected = _select_key_sentences(candidates, sentence_count)

    selected_set = set(selected)

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
        if (text, start, end, heading_path) in selected_set
    )

    selected_indices = tuple(
        index
        for index, candidate in enumerate(candidates)
        if candidate in selected_set
    )

    return ExtractiveSummary(
        mode=mode,
        text="\n\n".join(sentence.text for sentence in sentences),
        sentences=sentences,
        requested_sentence_count=sentence_count,
        returned_sentence_count=len(sentences),
        truncated=len(sentences) < sentence_count,
        algorithm_version=EXTRACTIVE_SUMMARY_ALGORITHM_VERSION,
        source_fingerprint=_source_fingerprint(markdown),
        diagnostics=SelectionDiagnostics(
            candidate_count=len(candidates),
            selected_indices=selected_indices,
            scores=tuple(sentence.score for sentence in sentences),
            heading_paths=tuple(
                sentence.heading_path for sentence in sentences
            ),
            redundancy_threshold=0.85,
        ),
    )
