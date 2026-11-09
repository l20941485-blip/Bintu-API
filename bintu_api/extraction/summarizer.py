"""Sentence-aware, token-budgeted summarization utilities."""

from __future__ import annotations

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