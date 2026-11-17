"""Retrieval-oriented semantic chunking for RAG ingestion.

This module is intentionally separate from the legacy token-budget chunker.
The legacy chunker remains the default because it is stable and widely used;
semantic chunking is opt-in while its retrieval guarantees mature.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

try:
    from bintu_api.common.fetch import compute_approx_tokens as count_tokens
except ImportError:
    import math

    def count_tokens(text: str) -> int:
        if not text or not text.strip():
            return 0
        return math.ceil(len(text) / 4)


CHUNKER_VERSION = "semantic-v2"

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE_OPEN = re.compile(r"^(?:```|~~~)")
_URL = re.compile(r"https?://[^\s)]+")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)*\|?\s*$")


@dataclass(frozen=True)
class SemanticChunk:
    index: int
    text: str
    approx_tokens: int
    tokens: int
    chunk_strategy: str
    chunk_id: str
    heading_path: list[str] = field(default_factory=list)
    section_index: int = 0
    contains_code: bool = False
    contains_table: bool = False
    contains_links: bool = False
    link_count: int = 0
    source_url: str | None = None
    final_url: str | None = None
    content_sha256: str | None = None
    extracted_at: str | None = None


@dataclass(frozen=True)
class _Heading:
    offset: int
    level: int
    text: str
    path: tuple[str, ...]


def make_chunk_id(
    *,
    source_url: str,
    content_sha256: str,
    chunk_strategy: str,
    chunk_index: int,
    max_tokens: int | None = None,
    overlap_tokens: int | None = None,
) -> str:
    material = "\n".join(
        [
            CHUNKER_VERSION,
            source_url,
            content_sha256,
            chunk_strategy,
            "unset" if max_tokens is None else str(max_tokens),
            "unset" if overlap_tokens is None else str(overlap_tokens),
            str(chunk_index),
        ]
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _build_headings(text: str) -> list[_Heading]:
    headings: list[_Heading] = []
    stack: list[tuple[int, str]] = []
    offset = 0
    in_fence = False
    fence_marker = ""

    for line in text.splitlines(keepends=True):
        line_start = offset
        line_end = offset + len(line)
        stripped = line.strip()

        if not in_fence and _FENCE_OPEN.match(stripped):
            in_fence = True
            fence_marker = stripped[:3]
        elif in_fence and stripped.startswith(fence_marker):
            in_fence = False
            fence_marker = ""
        elif not in_fence:
            match = _HEADING.match(line.rstrip("\r\n"))
            if match:
                level = len(match.group(1))
                heading_text = match.group(2).strip()

                while stack and stack[-1][0] >= level:
                    stack.pop()

                stack.append((level, heading_text))
                headings.append(
                    _Heading(
                        offset=line_start,
                        level=level,
                        text=heading_text,
                        path=tuple(heading for _, heading in stack),
                    )
                )

        offset = line_end

    return headings


def _split_sections(
    text: str,
    headings: list[_Heading],
) -> list[tuple[int, int, tuple[str, ...]]]:
    if not headings:
        return [(0, len(text), ())] if text.strip() else []

    sections: list[tuple[int, int, tuple[str, ...]]] = []

    if headings[0].offset > 0:
        preamble = text[: headings[0].offset]
        if preamble.strip():
            sections.append((0, headings[0].offset, ()))

    for position, heading in enumerate(headings):
        start = heading.offset
        end = headings[position + 1].offset if position + 1 < len(headings) else len(text)
        sections.append((start, end, heading.path))

    return sections


def _is_table_block(block: str) -> bool:
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    return len(lines) >= 2 and all("|" in line for line in lines)


def _pack_lines(lines: list[str], max_tokens: int) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []

    for line in lines:
        candidate = "\n".join([*current, line])
        if current and count_tokens(candidate) > max_tokens:
            chunks.append("\n".join(current))
            current = [line]
        else:
            current.append(line)

    if current:
        chunks.append("\n".join(current))

    return chunks


def _split_oversized_table(block: str, max_tokens: int) -> list[str]:
    lines = [line for line in block.splitlines() if line.strip()]

    if len(lines) < 3 or not _TABLE_SEPARATOR.match(lines[1]):
        return _split_by_whitespace(block, max_tokens)

    header = "\n".join(lines[:2])
    rows = lines[2:]

    if any(count_tokens(f"{header}\n{row}") > max_tokens for row in rows):
        return _split_by_whitespace(block, max_tokens)

    row_budget = max(1, max_tokens - count_tokens(header) - 1)
    packed_rows = _pack_lines(rows, row_budget)
    return [f"{header}\n{packed}" for packed in packed_rows]


def _split_fenced_block(block: str, max_tokens: int) -> list[str]:
    if count_tokens(block) <= max_tokens:
        return [block]

    lines = block.splitlines()
    if len(lines) < 2:
        return _split_by_whitespace(block, max_tokens)

    opener = lines[0]
    closing = lines[-1] if lines[-1].strip().startswith("```") else "```"
    body_lines = lines[1:-1] if closing == lines[-1] else lines[1:]
    body = "\n".join(body_lines)
    body_budget = max(1, max_tokens - count_tokens(f"{opener}\n{closing}"))

    return [f"{opener}\n{piece}\n{closing}" for piece in _pack_lines(body.splitlines(), body_budget)]


def _split_by_whitespace(text: str, max_tokens: int) -> list[str]:
    chunks: list[str] = []
    start: int | None = None
    end = 0

    for match in re.finditer(r"\S+", text):
        if start is None:
            start, end = match.start(), match.end()
            continue

        if count_tokens(text[start : match.end()]) > max_tokens:
            chunks.append(text[start:end])
            start = match.start()

        end = match.end()

    if start is not None:
        chunks.append(text[start:end])

    return chunks


def _tail_overlap(text: str, overlap_tokens: int) -> str:
    words = text.split()
    if not words:
        return ""

    tail: list[str] = []
    for word in reversed(words):
        candidate = " ".join([word, *tail])
        if count_tokens(candidate) > overlap_tokens:
            break
        tail.insert(0, word)

    return " ".join(tail)


def _apply_overlap(
    chunks: list[str],
    max_tokens: int,
    overlap_tokens: int,
) -> list[str]:
    if overlap_tokens <= 0 or len(chunks) <= 1:
        return chunks

    result = [chunks[0]]

    for chunk in chunks[1:]:
        overlap = _tail_overlap(result[-1], overlap_tokens)
        candidate = f"{overlap}\n\n{chunk}" if overlap else chunk

        while overlap and count_tokens(candidate) > max_tokens:
            words = overlap.split()
            if len(words) <= 1:
                overlap = ""
                candidate = chunk
                break

            overlap = " ".join(words[1:])
            candidate = f"{overlap}\n\n{chunk}"

        result.append(candidate)

    return result


def _split_prose(prose: str, max_tokens: int) -> list[str]:
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", prose) if paragraph.strip()]

    pieces: list[str] = []

    for paragraph in paragraphs:
        if _is_table_block(paragraph):
            if count_tokens(paragraph) <= max_tokens:
                pieces.append(paragraph)
            else:
                pieces.extend(_split_oversized_table(paragraph, max_tokens))
            continue

        if count_tokens(paragraph) <= max_tokens:
            pieces.append(paragraph)
        else:
            pieces.extend(_split_by_whitespace(paragraph, max_tokens))

    return pieces


def _pack_pieces(pieces: list[str], max_tokens: int) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []

    for piece in pieces:
        candidate = "\n\n".join([*current, piece])
        if current and count_tokens(candidate) > max_tokens:
            chunks.append("\n\n".join(current))
            current = [piece]
        else:
            current.append(piece)

    if current:
        chunks.append("\n\n".join(current))

    return chunks


def _split_section(
    section: str,
    *,
    max_tokens: int,
    overlap_tokens: int,
) -> list[str]:
    if count_tokens(section) <= max_tokens:
        return [section]

    pieces: list[str] = []
    cursor = 0

    for match in re.finditer(r"```.*?(?:```|\Z)", section, flags=re.DOTALL):
        prose = section[cursor : match.start()]
        if prose.strip():
            pieces.extend(_split_prose(prose, max_tokens))

        pieces.extend(_split_fenced_block(match.group(0), max_tokens))
        cursor = match.end()

    remainder = section[cursor:]
    if remainder.strip():
        pieces.extend(_split_prose(remainder, max_tokens))

    chunks = _pack_pieces(pieces, max_tokens)
    return _apply_overlap(chunks, max_tokens, overlap_tokens)


def split_semantic_chunks(
    text: str,
    *,
    max_tokens: int,
    overlap_tokens: int = 0,
    source_url: str | None = None,
    final_url: str | None = None,
    content_sha256: str | None = None,
    extracted_at: str | None = None,
) -> list[SemanticChunk]:
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")

    if overlap_tokens < 0:
        raise ValueError("overlap_tokens must be non-negative")

    if overlap_tokens >= max_tokens:
        raise ValueError("overlap_tokens must be less than max_tokens")

    if not text or not text.strip():
        return []

    headings = _build_headings(text)
    sections = _split_sections(text, headings)
    chunks: list[SemanticChunk] = []

    for section_index, (start, end, heading_path) in enumerate(sections):
        section = text[start:end].strip()
        if not section:
            continue

        pieces = _split_section(
            section,
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
        )

        for piece in pieces:
            chunk_index = len(chunks)
            links = _URL.findall(piece)

            chunks.append(
                SemanticChunk(
                    index=chunk_index,
                    text=piece,
                    approx_tokens=count_tokens(piece),
                    tokens=count_tokens(piece),
                    chunk_strategy="semantic",
                    chunk_id=make_chunk_id(
                        source_url=source_url or "",
                        content_sha256=content_sha256 or "",
                        chunk_strategy="semantic",
                        chunk_index=chunk_index,
                        max_tokens=max_tokens,
                        overlap_tokens=overlap_tokens,
                    ),
                    heading_path=list(heading_path),
                    section_index=section_index,
                    contains_code="```" in piece,
                    contains_table="|" in piece,
                    contains_links=bool(links),
                    link_count=len(links),
                    source_url=source_url,
                    final_url=final_url or source_url,
                    content_sha256=content_sha256,
                    extracted_at=extracted_at,
                )
            )

    return chunks
