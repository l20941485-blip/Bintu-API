"""VERBATIM copy of the current helpers from bintu_api/context.py (as pasted),
with count_tokens inlined. Used only so tests can show the old behaviour next
to the fixed behaviour. Do not import this in production code."""
from __future__ import annotations

import math
import re


def count_tokens(text: str) -> int:
    if not text or not text.strip():
        return 0
    return math.ceil(len(text) / 4)


def _sentences(text: str) -> list[str]:
    """Split prose into sentences while preserving terminal punctuation."""
    sentence_pattern = re.compile(
        r"""
        (?P<sentence>
            [^.!?]+            # sentence body
            [.!?]+             # terminal punctuation
            ["')\]]*           # optional closing quotes/brackets
        )
        (?P<space>\s+|$)
        """,
        re.VERBOSE,
    )

    sentences: list[str] = []
    position = 0

    for match in sentence_pattern.finditer(text):
        if match.start() > position:
            remainder = text[position : match.start()].strip()
            if remainder:
                sentences.append(remainder)
        sentences.append(match.group("sentence").strip())
        position = match.end()

    if position < len(text):
        remainder = text[position:].strip()
        if remainder:
            sentences.append(remainder)

    return [sentence for sentence in sentences if sentence]


def _is_table_block(block: str) -> bool:
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    return len(lines) >= 2 and all("|" in line for line in lines)


def _pack_chunk_pieces(pieces: list[str], max_tokens: int, separator: str) -> list[str]:
    chunks: list[str] = []
    current = ""

    for piece in pieces:
        if not piece:
            continue

        candidate = current + separator + piece if current else piece
        if current and count_tokens(candidate) > max_tokens:
            chunks.append(current)
            current = piece
        else:
            current = candidate

    if current:
        chunks.append(current)

    return chunks


def _split_oversized_table(block: str, max_tokens: int) -> list[str]:
    lines = [line for line in block.splitlines() if line.strip()]
    return _pack_chunk_pieces(lines, max_tokens, "\n")


def _split_at_whitespace(block: str, max_tokens: int) -> list[str]:
    chunks: list[str] = []
    start: int | None = None
    end = 0

    for match in re.finditer(r"\S+", block):
        if start is None:
            start = match.start()
            end = match.end()
            continue

        candidate = block[start : match.end()]
        if count_tokens(candidate) > max_tokens:
            chunks.append(block[start:end])
            start = match.start()

        end = match.end()

    if start is not None:
        chunks.append(block[start:end])

    return chunks


def _split_prose_block(block: str, max_tokens: int) -> list[str]:
    if count_tokens(block) <= max_tokens:
        return [block]

    sentences: list[str] = []
    position = 0
    boundary_pattern = re.compile(r"""[.!?]+["')\]]*\s+""")

    for match in boundary_pattern.finditer(block):
        sentence = block[position : match.end()].strip()
        if sentence:
            sentences.append(sentence)
        position = match.end()

    remainder = block[position:].strip()
    if remainder:
        sentences.append(remainder)

    pieces: list[str] = []
    for sentence in sentences:
        if count_tokens(sentence) <= max_tokens:
            pieces.append(sentence)
        else:
            pieces.extend(_split_at_whitespace(sentence, max_tokens))

    return _pack_chunk_pieces(pieces, max_tokens, " ")


def _split_block(block: str, max_tokens: int) -> list[str]:
    if count_tokens(block) <= max_tokens:
        return [block]

    if _is_table_block(block):
        return _split_oversized_table(block, max_tokens)

    sections: list[tuple[bool, str]] = []
    current_lines: list[str] = []
    current_has_pipe: bool | None = None

    for line in block.splitlines():
        has_pipe = "|" in line

        if current_lines and has_pipe != current_has_pipe:
            sections.append((bool(current_has_pipe), "\n".join(current_lines)))
            current_lines = []

        current_lines.append(line)
        current_has_pipe = has_pipe

    if current_lines:
        sections.append((bool(current_has_pipe), "\n".join(current_lines)))

    pieces: list[str] = []
    for has_pipe, section in sections:
        if has_pipe and _is_table_block(section):
            pieces.extend(_split_oversized_table(section, max_tokens))
        else:
            pieces.extend(_split_prose_block(section, max_tokens))

    return _pack_chunk_pieces(pieces, max_tokens, "\n")


def split_into_chunks(text: str, max_tokens: int) -> list[str]:
    if not text:
        return []
    if max_tokens <= 0:
        return [text]

    segments = re.split(r"(```.*?(?:```|\Z))", text, flags=re.DOTALL)
    pieces: list[str] = []

    for index, segment in enumerate(segments):
        if not segment.strip():
            continue

        if index % 2 == 1:
            fence_lines = segment.strip().splitlines()
            opener = fence_lines[0]
            body_lines = (
                fence_lines[1:-1]
                if len(fence_lines) > 1 and fence_lines[-1].startswith("```")
                else fence_lines[1:]
            )
            body = "\n".join(body_lines)

            fence_overhead = count_tokens(f"{opener}\n```\n")
            body_budget = max(1, max_tokens - fence_overhead)

            for body_chunk in _split_block(body, body_budget):
                pieces.append(f"{opener}\n{body_chunk}\n```")
            continue

        pieces.extend(_split_block(segment, max_tokens))

    return _pack_chunk_pieces(pieces, max_tokens, "\n\n")


def baseline_summarize(raw_text: str, max_tokens: int) -> str:
    """The summarize branch of extract_context(), extracted as a function."""
    if count_tokens(raw_text) <= max_tokens:
        return raw_text
    selected: list[str] = []
    used = 0
    for sentence in _sentences(raw_text):
        sentence_tokens = count_tokens(sentence)
        if used + sentence_tokens > max_tokens and selected:
            break
        selected.append(sentence)
        used += sentence_tokens
    final_text = " ".join(selected)
    char_budget = max_tokens * 4
    if count_tokens(final_text) > max_tokens and char_budget > 1:
        cut = final_text[: char_budget - 1]
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        final_text = cut.rstrip() + "\u2026"
    return final_text
