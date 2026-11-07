from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class SectionSelection:
    sections: list[dict[str, Any]]
    text: str
    truncated: bool


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$", re.MULTILINE)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def _parse_headings(text: str) -> list[dict[str, Any]]:
    headings: list[dict[str, Any]] = []

    for line_index, line in enumerate(text.split("\n")):
        match = _HEADING_RE.match(line)
        if not match:
            continue

        level = len(match.group(1))
        heading = match.group(2).strip()

        headings.append(
            {
                "ordinal": len(headings),
                "line_index": line_index,
                "level": level,
                "heading": heading,
                "normalized": _normalize(heading),
            }
        )

    return headings


def normalize_selectors(sections: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []

    for raw in sections:
        normalized = _normalize(raw)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)

    return result


def select_sections(
    text: str,
    sections: list[str],
    max_tokens: int,
) -> SectionSelection:
    selectors = normalize_selectors(sections)
    headings = _parse_headings(text)

    if not selectors or not headings:
        return SectionSelection(sections=[], text="", truncated=False)

    matched: list[dict[str, Any]] = []
    matched_ordinals: set[int] = set()

    for selector in selectors:
        for heading in headings:
            if heading["ordinal"] in matched_ordinals:
                continue

            if heading["normalized"] == selector:
                matched.append(heading)
                matched_ordinals.add(heading["ordinal"])
                break

    matched.sort(key=lambda heading: heading["ordinal"])

    if not matched:
        return SectionSelection(sections=[], text="", truncated=False)

    lines = text.split("\n")
    selected: list[dict[str, Any]] = []
    selected_texts: list[str] = []

    for heading in matched:
        start = heading["line_index"]
        end = len(lines)

        for later_heading in headings:
            if later_heading["line_index"] <= start:
                continue

            if later_heading["level"] <= heading["level"]:
                end = later_heading["line_index"]
                break

        section_text = "\n".join(lines[start:end]).strip()
        selected_texts.append(section_text)

        selected.append(
            {
                "heading": heading["heading"],
                "level": heading["level"],
                "index": heading["ordinal"],
                "text": section_text,
            }
        )

    max_chars = max_tokens * 4
    remaining = max_chars
    clipped: list[str] = []
    truncated = False

    for section_text in selected_texts:
        separator_cost = 2 if clipped else 0
        available = remaining - separator_cost

        if available <= 0:
            clipped.append("")
            truncated = True
            continue

        if len(section_text) <= available:
            clipped.append(section_text)
            remaining -= separator_cost + len(section_text)
        else:
            clipped.append(section_text[:available])
            remaining = 0
            truncated = True

    for section, clipped_text in zip(selected, clipped, strict=False):
        section["text"] = clipped_text

    return SectionSelection(
        sections=selected,
        text="\n\n".join(clipped),
        truncated=truncated,
    )
