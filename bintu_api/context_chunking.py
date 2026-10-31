"""Drop-in chunking / summarize helpers for bintu_api/context.py.

What this fixes (all reproduced against a verbatim copy of the current code in
test_context_chunking.py):

* summarize: "example. org" / "icann. org"  -> _sentences() regex cannot match a
  sentence that contains a dot inside a domain, emits the leftover text as its
  own "sentence", and " ".join() then inserts a space.
* summarize + chunk: headings glued to the previous sentence ("... purposes.
  ## Example domains") -> sentences were joined with " ", which turns the
  newline in front of a heading into a space. Fix: work line by line and join
  lines with "\\n"; only split a line into sentences when the line itself is
  over budget.
* chunk: extra blank lines around code fences and chunks that start with "\\n"
  -> prose segments around a fence kept their leading/trailing newline and were
  then joined with "\\n\\n".
* chunk: oversized fenced code containing "|" (shell pipes) was treated as a
  table / prose and re-joined with spaces. Code is now split by lines.
* chunk: a heading could end a chunk with its body in the next one.
* chunk: a line ending in ":" ("For example:") could be separated from the code
  fence it introduces; now it moves to the next chunk when it fits.
* chunk: a table split across chunks lost its header row; the header and
  separator rows are now repeated in every continuation piece.

Integration (edits in bintu_api/context.py):

    from bintu_api.context_chunking import split_into_chunks, summarize_text
    # delete: _sentences, _pack_chunk_pieces, _split_* helpers, split_into_chunks

    # summarize branch:
    final_text, was_truncated = summarize_text(raw_text, max_tokens)
    ...
    transformation_truncated = was_truncated or content_truncated
    if was_truncated:
        limiting_factor = "token_budget"

    # chunk branch: report the sum of chunk tokens, not the joined text with
    # separators (that is where the 6-8 token gap comes from)
    approx_tokens = sum(chunk["tokens"] for chunk in chunks)
"""
from __future__ import annotations

import math
import re

try:  # same estimator as the rest of the service
    from bintu_api.scraper import _compute_approx_tokens as count_tokens
except ImportError:  # standalone use and tests

    def count_tokens(text: str) -> int:
        if not text or not text.strip():
            return 0
        return math.ceil(len(text) / 4)


_HEADING_LINE = re.compile(r"^#{1,6}\s+\S")
_FENCE_SPLIT = re.compile(r"(```.*?(?:```|\Z))", re.DOTALL)
_BOUNDARY = re.compile(r"""[.!?]+["')\]]*\s+""")
_ABBREVIATIONS = {"mr", "mrs", "ms", "dr", "prof", "st", "vs", "etc", "no", "fig", "e.g", "i.e", "u.s"}


# --------------------------------------------------------------------------
# sentence / whitespace splitting
# --------------------------------------------------------------------------


def sentence_pieces(line: str) -> list[str]:
    """Split one line into sentences. A boundary needs whitespace after the
    punctuation, so example.org and URLs never split; common abbreviations and
    single-letter initials are skipped."""
    pieces: list[str] = []
    start = 0
    for match in _BOUNDARY.finditer(line):
        candidate = line[start : match.end()]
        last = candidate.split()[-1].rstrip(".!?\"')]").lower()
        if last in _ABBREVIATIONS or re.fullmatch(r"[a-z]", last):
            continue
        pieces.append(candidate.strip())
        start = match.end()
    remainder = line[start:].strip()
    if remainder:
        pieces.append(remainder)
    return [piece for piece in pieces if piece]


def _split_at_whitespace(block: str, max_tokens: int) -> list[str]:
    chunks: list[str] = []
    start: int | None = None
    end = 0
    for match in re.finditer(r"\S+", block):
        if start is None:
            start, end = match.start(), match.end()
            continue
        if count_tokens(block[start : match.end()]) > max_tokens:
            chunks.append(block[start:end])
            start = match.start()
        end = match.end()
    if start is not None:
        chunks.append(block[start:end])
    return chunks


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


def split_long_line(line: str, max_tokens: int) -> list[str]:
    """A single line over budget: whole sentences first, then whitespace."""
    pieces: list[str] = []
    for sentence in sentence_pieces(line):
        if count_tokens(sentence) <= max_tokens:
            pieces.append(sentence)
        else:
            pieces.extend(_split_at_whitespace(sentence, max_tokens))
    return _pack_chunk_pieces(pieces, max_tokens, " ")


def split_prose_block(block: str, max_tokens: int) -> list[str]:
    """Line-first splitting: newlines (and therefore headings) are preserved."""
    if count_tokens(block) <= max_tokens:
        return [block]
    pieces: list[str] = []
    for line in block.split("\n"):
        if not line.strip():
            continue
        if count_tokens(line) <= max_tokens:
            pieces.append(line)
        else:
            pieces.extend(split_long_line(line, max_tokens))
    return _pack_chunk_pieces(pieces, max_tokens, "\n")


# --------------------------------------------------------------------------
# tables and code
# --------------------------------------------------------------------------


def _is_table_block(block: str) -> bool:
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    return len(lines) >= 2 and all("|" in line for line in lines)


_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)*\|?\s*$")


def _split_oversized_table(block: str, max_tokens: int) -> list[str]:
    """Split a table by rows. When the table has a header + separator row, repeat
    both at the top of every piece so each chunk is self-describing for retrieval.
    Falls back to plain row packing when there is no header or a header plus a
    single row would not fit the budget."""
    lines = [line for line in block.splitlines() if line.strip()]
    plain = _pack_chunk_pieces(lines, max_tokens, "\n")
    if len(lines) < 3 or "|" not in lines[0] or not _TABLE_SEPARATOR.match(lines[1]):
        return plain

    header = "\n".join(lines[:2])
    rows = lines[2:]
    if any(count_tokens(f"{header}\n{row}") > max_tokens for row in rows):
        return plain
    row_budget = max_tokens - count_tokens(header) - 1
    return [f"{header}\n{packed}" for packed in _pack_chunk_pieces(rows, row_budget, "\n")]


def split_code_body(body: str, max_tokens: int) -> list[str]:
    """Oversized code: split by lines (never by sentences), long lines at whitespace."""
    if count_tokens(body) <= max_tokens:
        return [body]
    pieces: list[str] = []
    for line in body.split("\n"):
        if count_tokens(line) <= max_tokens:
            pieces.append(line)
        else:
            pieces.extend(_split_at_whitespace(line, max_tokens))
    return _pack_chunk_pieces(pieces, max_tokens, "\n")


def _split_fence(segment: str, max_tokens: int) -> list[str]:
    fence = segment.strip()
    if count_tokens(fence) <= max_tokens:
        return [fence]
    fence_lines = fence.splitlines()
    opener = fence_lines[0]
    body_lines = (
        fence_lines[1:-1]
        if len(fence_lines) > 1 and fence_lines[-1].startswith("```")
        else fence_lines[1:]
    )
    body = "\n".join(body_lines)
    body_budget = max(1, max_tokens - count_tokens(f"{opener}\n```\n"))
    return [f"{opener}\n{part}\n```" for part in split_code_body(body, body_budget)]


def _split_oversized_table_like_block(
    block: str, max_tokens: int
) -> list[str] | None:
    """Split extracted tables whose header/separator omit Markdown pipes.

    The extractor can emit:

        Country
        ---
        cell | cell | cell

    Treat the first line as the header, the second as its separator, and
    split oversized pipe-joined rows by cells while repeating the header.
    """
    lines = [line for line in block.splitlines() if line.strip()]
    if len(lines) < 3 or not _TABLE_SEPARATOR.match(lines[1]):
        return None

    header = f"{lines[0]}\n{lines[1]}"
    header_tokens = count_tokens(header) + 1
    if header_tokens >= max_tokens:
        return None

    pieces: list[str] = []
    current: list[str] = []

    for row in lines[2:]:
        cells = [row]
        if count_tokens(f"{header}\n{row}") > max_tokens and " | " in row:
            cells = row.split(" | ")

        if any(count_tokens(cell) + header_tokens > max_tokens for cell in cells):
            return None

        for cell in cells:
            candidate = current + [cell]
            candidate_text = header + "\n" + " | ".join(candidate)
            if current and count_tokens(candidate_text) > max_tokens:
                pieces.append(header + "\n" + " | ".join(current))
                current = [cell]
            else:
                current = candidate

    if current:
        pieces.append(header + "\n" + " | ".join(current))

    return pieces


def split_block(block: str, max_tokens: int) -> list[str]:
    """Separate table runs from prose, then split each with its own rules."""
    if count_tokens(block) <= max_tokens:
        return [block]

    if _is_table_block(block):
        return _split_oversized_table(block, max_tokens)

    # Handle the extractor's pipe-less header/separator shape:
    #   Country
    #   ---
    #   cell | cell | cell
    # Normal Markdown pipe tables remain on the existing row-splitting path.
    table_like = _split_oversized_table_like_block(block, max_tokens)
    if table_like is not None:
        return table_like

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
            pieces.extend(split_prose_block(section, max_tokens))
    return _pack_chunk_pieces(pieces, max_tokens, "\n")


# --------------------------------------------------------------------------
# chunking
# --------------------------------------------------------------------------


def _keep_lead_ins(chunks: list[str], max_tokens: int) -> list[str]:
    """Keep lead-in lines attached to what they introduce.

    * a heading that ends a chunk moves to the start of the next chunk;
    * a line ending in ":" moves to the next chunk when that chunk starts with a
      code fence ("For example:" stays with its example).
    A move is skipped when the next chunk would exceed the budget.
    """
    chunks = list(chunks)
    for _ in range(4):  # headings and colon lines can chain
        changed = False
        for index in range(len(chunks) - 1):
            lines = chunks[index].split("\n")
            if len(lines) < 2:
                continue
            last = lines[-1]
            introduces_fence = last.rstrip().endswith(":") and chunks[index + 1].startswith("```")
            if _HEADING_LINE.match(last) or introduces_fence:
                moved = f"{last}\n{chunks[index + 1]}"
                if count_tokens(moved) <= max_tokens:
                    chunks[index] = "\n".join(lines[:-1])
                    chunks[index + 1] = moved
                    changed = True
        if not changed:
            break
    return chunks


_keep_headings_with_body = _keep_lead_ins  # backwards-compatible name


def split_into_chunks(text: str, max_tokens: int, *, keep_lead_ins: bool = True) -> list[str]:
    """Token-budgeted chunks. Fences are atomic when they fit, split with balanced
    fences when they do not. Chunks are joined line-by-line with single newlines.
    Tables that must be split repeat their header row in every piece."""
    if not text:
        return []
    if max_tokens <= 0:
        return [text]

    pieces: list[str] = []
    for index, segment in enumerate(_FENCE_SPLIT.split(text)):
        if index % 2 == 1:
            pieces.extend(_split_fence(segment, max_tokens))
            continue
        segment = segment.strip("\n")
        if segment.strip():
            pieces.extend(split_block(segment, max_tokens))

    chunks = _pack_chunk_pieces(pieces, max_tokens, "\n")
    return _keep_lead_ins(chunks, max_tokens) if keep_lead_ins else chunks


# --------------------------------------------------------------------------
# summarize (leading text, line by line, sentence-aware at the cut)
# --------------------------------------------------------------------------


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
    includes whole lines while they fit, then whole sentences of the first line
    that does not fit. Never ends on a heading and never leaves a fence open.
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
