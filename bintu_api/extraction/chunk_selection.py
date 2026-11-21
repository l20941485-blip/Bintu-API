"""Deterministic selection of chunks within an overall response budget."""

from __future__ import annotations

from typing import Any, Literal

ChunkSelectionPolicy = Literal["all", "first"]


def select_chunks_for_budget(
    chunks: list[dict[str, Any]],
    *,
    max_tokens: int,
    policy: ChunkSelectionPolicy = "all",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Select chunks in document order without exceeding ``max_tokens``.

    The first chunk is always retained so a valid non-empty extraction does not
    become empty merely because its first chunk fills the budget. Chunks that
    cannot fit are returned separately for omission reporting.
    """
    if policy not in ("all", "first"):
        raise ValueError(f"Unsupported chunk selection policy: {policy}")

    selected: list[dict[str, Any]] = []
    omitted: list[dict[str, Any]] = []
    total_tokens = 0

    if policy == "all":
        return list(chunks), []

    for index, chunk in enumerate(chunks):
        tokens = int(
            chunk.get("tokens")
            or chunk.get("approx_tokens")
            or 0
        )

        if index == 0:
            selected.append(chunk)
            total_tokens += tokens
            continue

        if total_tokens + tokens <= max_tokens:
            selected.append(chunk)
            total_tokens += tokens
        else:
            omitted.append(chunk)

    return selected, omitted


def omitted_sections(chunks: list[dict[str, Any]]) -> list[str]:
    """Return unique heading paths for omitted chunks, in document order."""
    sections: list[str] = []
    seen: set[tuple[str, ...]] = set()

    for chunk in chunks:
        heading_path = tuple(chunk.get("heading_path") or [])
        if not heading_path or heading_path in seen:
            continue

        seen.add(heading_path)
        sections.append(" > ".join(heading_path))

    return sections
