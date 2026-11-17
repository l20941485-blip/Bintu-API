"""Retrieval-oriented semantic chunking for RAG ingestion.

This module is intentionally separate from the legacy token-budget chunker.
The legacy chunker remains the default because it is stable and widely used;
semantic chunking is opt-in while its retrieval guarantees mature.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

try:  # Use the service-wide estimator when available.
    from bintu_api.common.fetch import compute_approx_tokens as count_tokens
except ImportError:  # Standalone use and tests.
    import math

    def count_tokens(text: str) -> int:
        if not text or not text.strip():
            return 0
        return math.ceil(len(text) / 4)


_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.MULTILINE)
_FENCE = re.compile(r"```")
_URL = re.compile(r"https?://[^\s)]+")


@dataclass(frozen=True)
class SemanticChunk:
    """A self-contained chunk suitable for vector retrieval."""

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


def make_chunk_id(
    *,
    source_url: str,
    content_sha256: str,
    chunk_strategy: str,
    chunk_index: int,
) -> str:
    """Return a deterministic ID for one retrieval chunk."""
    material = "\n".join(
        [
            source_url,
            content_sha256,
            chunk_strategy,
            str(chunk_index),
        ]
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _build_heading_index(text: str) -> list[tuple[int, int, str]]:
    """Return (offset, level, heading text) for headings outside code fences."""
    headings: list[tuple[int, int, str]] = []
    in_fence = False

    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        match = _HEADING.match(line)
        if match:
            headings.append(
                (
                    text.find(line),
                    len(match.group(1)),
                    match.group(2).strip(),
                )
            )

    return headings


def _heading_path_for_offset(
    headings: list[tuple[int, int, str]],
    offset: int,
) -> list[str]:
    """Return the heading chain enclosing an offset."""
    selected: dict[int, str] = {}

    for heading_offset, level, heading_text in headings:
        if heading_offset > offset:
            break
        selected[level] = heading_text

    return [selected[level] for level in sorted(selected)]


def _split_sections(text: str) -> list[str]:
    """Split Markdown into heading-delimited sections."""
    matches = list(_HEADING.finditer(text))

    if not matches:
        return [text.strip()] if text.strip() else []

    sections: list[str] = []

    preamble = text[: matches[0].start()].strip()
    if preamble:
        sections.append(preamble)

    for position, match in enumerate(matches):
        start = match.start()
        end = matches[position + 1].start() if position + 1 < len(matches) else len(text)
        section = text[start:end].strip()
        if section:
            sections.append(section)

    return sections


def _split_oversized_section(
    section: str,
    max_tokens: int,
    overlap_tokens: int,
) -> list[str]:
    """Split one oversized section by paragraphs, then whitespace."""
    paragraphs = [paragraph.strip() for paragraph in section.split("\n\n") if paragraph.strip()]

    if len(paragraphs) <= 1:
        return _split_by_whitespace(section, max_tokens)

    chunks: list[str] = []
    current: list[str] = []

    for paragraph in paragraphs:
        candidate = "\n\n".join([*current, paragraph])
        if current and count_tokens(candidate) > max_tokens:
            chunks.append("\n\n".join(current))
            current = [paragraph]
        else:
            current.append(paragraph)

    if current:
        chunks.append("\n\n".join(current))

    if overlap_tokens and len(chunks) > 1:
        overlapped: list[str] = [chunks[0]]

        for index in range(1, len(chunks)):
            previous = chunks[index - 1]
            overlap = _split_by_whitespace(previous, overlap_tokens)[0]
            overlapped.append(f"{overlap}\n\n{chunks[index]}")

        return overlapped

    return chunks


def _split_by_whitespace(text: str, max_tokens: int) -> list[str]:
    """Split text at whitespace without breaking words or URLs."""
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
    """Split Markdown into heading-aligned, retrieval-ready chunks."""
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")

    if overlap_tokens < 0:
        raise ValueError("overlap_tokens must be non-negative")

    if overlap_tokens >= max_tokens:
        raise ValueError("overlap_tokens must be less than max_tokens")

    if not text or not text.strip():
        return []

    sections = _split_sections(text)
    headings = _build_heading_index(text)
    chunks: list[SemanticChunk] = []

    for section_index, section in enumerate(sections):
        if count_tokens(section) <= max_tokens:
            pieces = [section]
        else:
            pieces = _split_oversized_section(
                section,
                max_tokens=max_tokens,
                overlap_tokens=overlap_tokens,
            )

        section_heading_path = _heading_path_for_offset(
            headings,
            text.find(section),
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
                    ),
                    heading_path=section_heading_path,
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
