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
_LIST_LABEL_RE = re.compile(
    r"^\s*[-*+]\s+\*\*(.*?)\*\*\s*$",
    re.MULTILINE,
)


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


def _parse_list_labels(text: str) -> list[dict[str, Any]]:
    labels: list[dict[str, Any]] = []

    for line_index, line in enumerate(text.split("\n")):
        match = _LIST_LABEL_RE.match(line)
        if not match:
            continue

        label = match.group(1).strip()

        labels.append(
            {
                "ordinal": len(labels),
                "line_index": line_index,
                "label": label,
                "normalized": _normalize(label),
            }
        )

    return labels


def normalize_selectors(sections: str | list[str]) -> list[str]:
    if isinstance(sections, str):
        raw_values = sections.split("\n")
    else:
        raw_values = sections

    seen: set[str] = set()
    result: list[str] = []

    for raw in raw_values:
        normalized = _normalize(raw)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)

    return result


def select_sections(
    text: str,
    sections: str | list[str],
    max_tokens: int,
) -> SectionSelection:
    selectors = normalize_selectors(sections)
    headings = _parse_headings(text)

    if not selectors:
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
        list_labels = _parse_list_labels(text)
        matched_labels: list[dict[str, Any]] = []
        matched_label_ordinals: set[int] = set()

        for selector in selectors:
            for label in list_labels:
                if label["ordinal"] in matched_label_ordinals:
                    continue

                if label["normalized"] == selector:
                    matched_labels.append(label)
                    matched_label_ordinals.add(label["ordinal"])
                    break

        if matched_labels:
            lines = text.split("\n")
            selected: list[dict[str, Any]] = []
            selected_texts: list[str] = []

            for label in matched_labels:
                start = label["line_index"] + 1
                end = len(lines)

                for later_label in list_labels:
                    if later_label["line_index"] <= start:
                        continue

                    end = later_label["line_index"]
                    break

                section_text = "\n".join(lines[start:end]).strip()
                selected_texts.append(section_text)

                selected.append(
                    {
                        "heading": label["label"],
                        "level": 0,
                        "index": label["ordinal"],
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

        blocks = [
            block.strip()
            for block in re.split(r"\n\s*\n", text)
            if block.strip()
        ]

        for block in blocks:
            normalized_block = _normalize(block)
            if normalized_block in selectors:
                return SectionSelection(
                    sections=[
                        {
                            "heading": block.splitlines()[0][:200],
                            "level": 0,
                            "index": 0,
                            "text": block,
                        }
                    ],
                    text=block,
                    truncated=False,
                )

        return SectionSelection(sections=[], text="", truncated=False)

    lines = text.split("\n")
    selected: list[dict[str, Any]] = []
    selected_texts: list[str] = []

    for heading in matched:
        start = heading["line_index"] + 1
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
