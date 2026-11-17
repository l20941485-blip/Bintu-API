from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class SectionSelection:
    sections: list[dict[str, Any]]
    text: str
    truncated: bool
    requested_sections: tuple[str, ...] = ()
    unmatched_sections: tuple[str, ...] = ()
    available_sections: tuple[str, ...] = ()
    filtered: bool = False
    match_status: str = "not_filtered"
    warnings: tuple[str, ...] = ()
    requested_sections: tuple[str, ...] = ()
    unmatched_sections: tuple[str, ...] = ()
    available_sections: tuple[str, ...] = ()
    filtered: bool = False
    match_status: str = "not_filtered"
    warnings: tuple[str, ...] = ()


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$", re.MULTILINE)
_LIST_LABEL_RE = re.compile(
    r"^\s*[-*+]\s+\*\*(.*?)\*\*\s*$",
    re.MULTILINE,
)
_PLAIN_LABEL_RE = re.compile(
    r"^(.+?)(?:\s+\((?:https?://|www\.)[^\s)]+\))?$"
)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def _normalize_heading(value: str) -> str:
    normalized = _normalize(value)
    return re.sub(r"\s*\[edit\]\s*$", "", normalized).strip()


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


def _is_plain_label(line: str) -> bool:
    stripped = line.strip()

    if not stripped or len(stripped) > 200:
        return False

    if re.search(r"[.!?]\s*$", stripped):
        return False

    if ", " in stripped:
        return False

    return bool(_PLAIN_LABEL_RE.match(stripped))


def _parse_plain_labels(text: str) -> list[dict[str, Any]]:
    labels: list[dict[str, Any]] = []

    for line_index, line in enumerate(text.split("\n")):
        stripped = line.strip()

        if not _is_plain_label(stripped):
            continue

        match = _PLAIN_LABEL_RE.match(stripped)
        label = match.group(1).strip()
        normalized = _normalize(label)

        if not normalized:
            continue

        labels.append(
            {
                "ordinal": len(labels),
                "line_index": line_index,
                "label": label,
                "normalized": normalized,
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


def _select_sections_core(
    text: str,
    sections: str | list[str],
    max_tokens: int | None,
) -> SectionSelection:
    selectors = normalize_selectors(sections)
    headings = _parse_headings(text)

    # `None` means "select the complete matching sections." The caller is
    # responsible for applying its own mode-specific budget afterward:
    # chunk mode budgets individual chunks, while summarize mode budgets
    # its summary. This prevents section selection from discarding content
    # before chunking or summarizing.
    if max_tokens is None:
        max_tokens = max(1, -(-len(text) // 4))

    if not selectors:
        return SectionSelection(sections=[], text="", truncated=False)

    matched: list[dict[str, Any]] = []
    matched_ordinals: set[int] = set()

    for selector in selectors:
        for heading in headings:
            if heading["ordinal"] in matched_ordinals:
                continue

            heading_normalized = _normalize_heading(heading["heading"])

            if heading_normalized == selector:
                matched.append(heading)
                matched_ordinals.add(heading["ordinal"])
                break

            if heading_normalized.startswith(selector):
                matched.append(heading)
                matched_ordinals.add(heading["ordinal"])
                break

            if selector in heading_normalized:
                matched.append(heading)
                matched_ordinals.add(heading["ordinal"])
                break

    matched.sort(key=lambda heading: heading["ordinal"])    

    if not matched:
        plain_labels = _parse_plain_labels(text)
        matched_plain_labels: list[dict[str, Any]] = []
        matched_plain_ordinals: set[int] = set()

        for selector in selectors:
            for label in plain_labels:
                if label["ordinal"] in matched_plain_ordinals:
                    continue

                if label["normalized"] == selector:
                    matched_plain_labels.append(label)
                    matched_plain_ordinals.add(label["ordinal"])
                    break

        if matched_plain_labels:
            lines = text.split("\n")
            selected: list[dict[str, Any]] = []
            selected_texts: list[str] = []

            for label in matched_plain_labels:
                start = label["line_index"]
                end = len(lines)

                for later_label in plain_labels:
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


def select_sections(
    text: str,
    sections: str | list[str],
    max_tokens: int | None,
) -> SectionSelection:
    """Select sections and return selection diagnostics.

    This wrapper preserves the established selection algorithm while adding
    metadata about requested, matched, unmatched, and available sections.
    """
    selectors = normalize_selectors(sections)
    selection = _select_sections_core(text, selectors, max_tokens)

    if not selectors:
        return selection

    headings = _parse_headings(text)
    list_labels = _parse_list_labels(text)
    plain_labels = _parse_plain_labels(text)

    available_sections = (
        [heading["heading"] for heading in headings]
        + [label["label"] for label in list_labels]
        + [label["label"] for label in plain_labels]
    )

    def matches(selector: str, candidate: str) -> bool:
        normalized = _normalize_heading(candidate)
        return (
            normalized == selector
            or normalized.startswith(selector)
            or selector in normalized
        )

    matched_selectors = [
        selector
        for selector in selectors
        if any(
            matches(selector, section["heading"])
            for section in selection.sections
        )
    ]
    unmatched_sections = [
        selector for selector in selectors if selector not in matched_selectors
    ]

    if not matched_selectors:
        match_status = "no_match"
    elif unmatched_sections:
        match_status = "partial_match"
    else:
        match_status = "matched"

    warnings = tuple(
        f"No section matched: {selector}." for selector in unmatched_sections
    )

    return SectionSelection(
        sections=selection.sections,
        text=selection.text,
        truncated=selection.truncated,
        requested_sections=tuple(selectors),
        unmatched_sections=tuple(unmatched_sections),
        available_sections=tuple(available_sections),
        filtered=True,
        match_status=match_status,
        warnings=warnings,
    )
