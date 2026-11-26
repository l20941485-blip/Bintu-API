"""Yield and low-yield assessment for Bintu extraction.

This module owns the low-yield detection rule (large page, almost no text,
low ratio) and the JavaScript-rendered hint logic. It is imported by the
extraction orchestrator and performs no network access.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

LOW_YIELD_MIN_HTML_TOKENS = 1000
LOW_YIELD_MAX_TEXT_TOKENS = 100
LOW_YIELD_MAX_RATIO = 0.05

_JS_MARKERS = (
    re.compile(
        r"""<div[^>]+id=["'](?:root|app|__next|__nuxt)["'][^>]*>\s*</div>""",
        re.IGNORECASE,
    ),
    re.compile(r"__NEXT_DATA__|__NUXT__|window\.__INITIAL_STATE__", re.IGNORECASE),
    re.compile(r"<noscript[^>]*>[^<]{0,200}javascript", re.IGNORECASE),
    re.compile(r"you need to enable javascript", re.IGNORECASE),
    re.compile(r"""<script[^>]*>\s*var\s+data\s*=\s*\[""", re.IGNORECASE), # inline data array (quotes.toscrape.com/js)
)

HINT_JAVASCRIPT = "This page returned little readable text because it appears to require JavaScript."
HINT_LITTLE_TEXT = "This page returned little readable text. It may require JavaScript or a login."


@dataclass(frozen=True)
class YieldAssessment:
    low_yield: bool
    reason: str | None = None
    hint: str | None = None
    ratio: float = 1.0


def assess_yield(extracted_tokens: int, html_tokens: int, html_text: str ="") -> YieldAssessment:
    ratio = (extracted_tokens / html_tokens) if html_tokens > 0 else 1.0
    low = (
        html_tokens >= LOW_YIELD_MIN_HTML_TOKENS
        and extracted_tokens <= LOW_YIELD_MAX_TEXT_TOKENS
        and ratio <= LOW_YIELD_MAX_RATIO
    )
    if not low:
        return YieldAssessment(False, None, None, round(ratio, 4))
    if html_text and any(pattern.search(html_text) for pattern in _JS_MARKERS):
        return YieldAssessment(True, "javascript_rendered", HINT_JAVASCRIPT, round(ratio, 4))
    return YieldAssessment(True, "little_text", HINT_LITTLE_TEXT, round(ratio, 4))
_BOILERPLATE_LINE_PATTERNS = (
    re.compile(
        r"^(?:references|external links|see also|further reading|bibliography|notes|citations)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:navigation|main menu|site navigation|footer|breadcrumbs|categories|tags)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:edit|edit source|history|talk|discussion|share|print|cite)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:skip to (?:main )?content|back to top|scroll to top)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:sign in|log in|sign up|subscribe|newsletter|cookie|privacy|terms|about|contact|careers)$",
        re.IGNORECASE,
    ),
)

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass(frozen=True)
class ContentQualityAssessment:
    score: float
    boilerplate_ratio: float
    main_content_coverage: float
    section_completeness: float
    policy: str = "observe"
    warnings: list[str] = field(default_factory=list)


def detect_boilerplate_characters(text: str) -> int:
    """Count characters in conservatively identified boilerplate lines."""
    line_counts: dict[str, int] = {}
    stripped_lines: list[str] = []

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        stripped_lines.append(stripped)
        if len(stripped) <= 80:
            key = stripped.casefold()
            line_counts[key] = line_counts.get(key, 0) + 1

    boilerplate = 0
    for stripped in stripped_lines:
        is_known_noise = any(
            pattern.fullmatch(stripped)
            for pattern in _BOILERPLATE_LINE_PATTERNS
        )
        is_repeated = (
            len(stripped) <= 80
            and line_counts.get(stripped.casefold(), 0) >= 3
        )

        if is_known_noise or is_repeated:
            boilerplate += len(stripped)

    return boilerplate


def _section_completeness(text: str) -> float:
    lines = text.splitlines()
    headings = [
        index
        for index, line in enumerate(lines)
        if _HEADING_RE.match(line.strip())
    ]

    if not headings:
        return 1.0

    complete = 0
    for position, heading_index in enumerate(headings):
        end = (
            headings[position + 1]
            if position + 1 < len(headings)
            else len(lines)
        )
        body = "\n".join(lines[heading_index + 1:end]).strip()
        if body:
            complete += 1

    return complete / len(headings)


def assess_content_quality(
    *,
    extracted_characters: int,
    boilerplate_characters: int,
    pre_cleaning_characters: int,
    total_sections: int,
    complete_sections: int,
) -> ContentQualityAssessment:
    """Calculate deterministic extraction-quality signals."""
    extracted_characters = max(int(extracted_characters or 0), 0)
    boilerplate_characters = max(int(boilerplate_characters or 0), 0)
    pre_cleaning_characters = max(int(pre_cleaning_characters or 0), 0)
    total_sections = max(int(total_sections or 0), 0)
    complete_sections = max(int(complete_sections or 0), 0)

    if extracted_characters == 0:
        return ContentQualityAssessment(0.0, 0.0, 0.0, 0.0)

    boilerplate_ratio = min(
        boilerplate_characters / extracted_characters,
        1.0,
    )
    main_content_coverage = (
        min(extracted_characters / pre_cleaning_characters, 1.0)
        if pre_cleaning_characters > 0
        else 1.0
    )

    if total_sections > 0:
        section_completeness = min(
            complete_sections / total_sections,
            1.0,
        )
    else:
        section_completeness = 1.0

    score = (
        0.45 * main_content_coverage
        + 0.30 * (1.0 - boilerplate_ratio)
        + 0.25 * section_completeness
    )

    return ContentQualityAssessment(
        score=round(min(max(score, 0.0), 1.0), 4),
        boilerplate_ratio=round(boilerplate_ratio, 4),
        main_content_coverage=round(main_content_coverage, 4),
        section_completeness=round(section_completeness, 4),
    )

QUALITY_POLICIES = ("observe", "warn", "enforce")
DEFAULT_QUALITY_MIN_SCORE = 0.5

_quality_logger = logging.getLogger("bintu_api.extraction.quality")


class ContentQualityPolicyError(ValueError):
    """Raised when enforced content quality falls below the configured threshold."""

    def __init__(self, assessment: ContentQualityAssessment, min_score: float, url: str = "") -> None:
        self.assessment = assessment
        self.min_score = min_score
        self.url = url
        super().__init__(
            f"Content quality score {assessment.score:.4f} is below minimum threshold {min_score:.4f}"
        )


def evaluate_content_quality_policy(
    assessment: ContentQualityAssessment,
    *,
    policy: str = "observe",
    min_score: float = DEFAULT_QUALITY_MIN_SCORE,
    url: str = "",
) -> ContentQualityAssessment:
    """Apply observe, warn, or enforce policy against a quality assessment."""
    if not isinstance(policy, str):
        normalized_policy = "observe"
    else:
        normalized_policy = (policy or "observe").strip().lower()
        if normalized_policy not in QUALITY_POLICIES:
            normalized_policy = "observe"

    warnings = []
    if assessment.score < min_score:
        warnings.append(f"quality_score_below_threshold:{min_score}")
    if assessment.boilerplate_ratio > 0.15:
        warnings.append("high_boilerplate_ratio")
    if assessment.main_content_coverage < 0.5:
        warnings.append("low_main_content_coverage")

    if normalized_policy == "observe" or assessment.score >= min_score:
        return ContentQualityAssessment(
            score=assessment.score,
            boilerplate_ratio=assessment.boilerplate_ratio,
            main_content_coverage=assessment.main_content_coverage,
            section_completeness=assessment.section_completeness,
            policy=normalized_policy,
            warnings=warnings,
        )

    if normalized_policy == "warn":
        _quality_logger.warning(
            "content_quality_below_threshold score=%.4f min_score=%.4f boilerplate_ratio=%.4f coverage=%.4f completeness=%.4f url=%s",
            assessment.score,
            min_score,
            assessment.boilerplate_ratio,
            assessment.main_content_coverage,
            assessment.section_completeness,
            url,
        )
        return ContentQualityAssessment(
            score=assessment.score,
            boilerplate_ratio=assessment.boilerplate_ratio,
            main_content_coverage=assessment.main_content_coverage,
            section_completeness=assessment.section_completeness,
            policy=normalized_policy,
            warnings=warnings,
        )

    raise ContentQualityPolicyError(assessment=assessment, min_score=min_score, url=url)
