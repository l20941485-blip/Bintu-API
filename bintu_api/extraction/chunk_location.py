"""Source-location provenance for extraction chunks."""

from __future__ import annotations

from typing import Any

from bintu_api.extraction.rag_chunking import build_headings


def annotate_chunk_locations(
    chunks: list[dict[str, Any]],
    *,
    source_text: str,
) -> list[dict[str, Any]]:
    """Attach best-effort source locations to chunk dictionaries.

    Offsets refer to the link-policy-filtered source text supplied by the
    caller. They are zero-based, and ``char_end`` is exclusive.

    A chunk is marked ``reassembled=True`` with null offsets when it cannot be
    located exactly. This can occur when sequential lead-in handling moves a
    heading or context line, or when semantic chunk normalization changes
    whitespace. Existing ``heading_path`` values are preserved.
    """
    headings = build_headings(source_text)
    annotated: list[dict[str, Any]] = []
    cursor = 0

    for chunk in chunks:
        text = str(chunk.get("text", ""))
        start = source_text.find(text, cursor)

        if start < 0:
            annotated.append(
                {
                    **chunk,
                    "char_start": None,
                    "char_end": None,
                    "reassembled": True,
                }
            )
            continue

        end = start + len(text)
        cursor = end

        if "heading_path" not in chunk:
            active_heading = next(
                (
                    heading
                    for heading in reversed(headings)
                    if heading.offset <= start
                ),
                None,
            )
            chunk = {
                **chunk,
                "heading_path": (
                    list(active_heading.path) if active_heading else []
                ),
            }

        annotated.append(
            {
                **chunk,
                "char_start": start,
                "char_end": end,
                "reassembled": False,
            }
        )

    return annotated
