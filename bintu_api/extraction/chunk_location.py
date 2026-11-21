"""Best-effort source-location provenance for sequential chunks."""

from __future__ import annotations

from typing import Any

from bintu_api.extraction.rag_chunking import _build_headings


def annotate_sequential_chunk_locations(
    chunks: list[dict[str, Any]],
    *,
    source_text: str,
) -> list[dict[str, Any]]:
    """Attach heading paths and best-effort offsets to sequential chunks.

    A chunk that cannot be located exactly, typically because ``keep_lead_ins``
    moved a heading or context line, receives ``reassembled=True`` and null
    offsets rather than an incorrect location.
    """
    headings = _build_headings(source_text)
    annotated: list[dict[str, Any]] = []
    cursor = 0

    for chunk in chunks:
        text = str(chunk.get("text", ""))
        start = source_text.find(text, cursor)

        if start < 0:
            annotated.append(
                {
                    **chunk,
                    "heading_path": [],
                    "char_start": None,
                    "char_end": None,
                    "reassembled": True,
                }
            )
            continue

        end = start + len(text)
        cursor = end

        active_heading = next(
            (
                heading
                for heading in reversed(headings)
                if heading.offset <= start
            ),
            None,
        )
        heading_path = list(active_heading.path) if active_heading else []

        annotated.append(
            {
                **chunk,
                "heading_path": heading_path,
                "char_start": start,
                "char_end": end,
                "reassembled": False,
            }
        )

    return annotated
