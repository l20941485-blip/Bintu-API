"""Explicit quality-policy decisions for extracted content.

This module evaluates an existing content-quality assessment. It does not
compute quality itself, access caches, fetch documents, or alter public
response schemas.
"""

from dataclasses import dataclass
from typing import Literal

from bintu_api.extraction.quality import ContentQualityAssessment

QUALITY_POLICY_VERSION = "v1"

QualityPolicyMode = Literal["observe", "warn", "enforce"]
QualityPolicyAction = Literal["return", "reject"]

VALID_QUALITY_POLICY_MODES = ("observe", "warn", "enforce")


@dataclass(frozen=True)
class QualityPolicy:
    """Caller-selectable quality policy for extraction results."""

    mode: QualityPolicyMode = "observe"
    minimum_score: float = 0.0


@dataclass(frozen=True)
class QualityPolicyDecision:
    """Deterministic outcome of applying a quality policy."""

    action: QualityPolicyAction
    warnings: tuple[str, ...] = ()


def evaluate_quality_policy(
    *,
    quality: ContentQualityAssessment,
    policy: QualityPolicy,
) -> QualityPolicyDecision:
    """Apply a quality policy to a quality assessment.

    ``observe`` always returns the result. ``warn`` returns the result and
    records a warning below the configured threshold. ``enforce`` rejects the
    result below the configured threshold.
    """
    if policy.mode not in VALID_QUALITY_POLICY_MODES:
        raise ValueError(
            "invalid_quality_policy_mode: "
            f"expected one of {VALID_QUALITY_POLICY_MODES}, "
            f"got {policy.mode!r}"
        )

    if policy.mode == "observe":
        return QualityPolicyDecision(action="return")

    below_threshold = quality.score < policy.minimum_score

    if policy.mode == "warn":
        if below_threshold:
            return QualityPolicyDecision(
                action="return",
                warnings=("quality_below_threshold",),
            )
        return QualityPolicyDecision(action="return")

    if below_threshold:
        return QualityPolicyDecision(
            action="reject",
            warnings=("quality_below_threshold",),
        )
    return QualityPolicyDecision(action="return")


class ExtractionQualityError(Exception):
    """Raised when extraction fails the configured quality policy."""

    def __init__(
        self,
        reason: str = "quality_policy_rejected",
        *,
        warnings: tuple[str, ...] = (),
        details: dict[str, object] | None = None,
    ) -> None:
        self.reason = reason
        self.warnings = warnings
        self.details = details or {}
        super().__init__(reason)


def enforce_quality_policy(
    *,
    text: str,
    extracted_tokens: int,
    html_tokens: int,
    quality: ContentQualityAssessment,
    policy: QualityPolicy,
    min_extracted_tokens: int | None = None,
    min_yield_ratio: float | None = None,
) -> QualityPolicyDecision:
    """Enforce a quality policy on extracted content and raise on rejection."""
    decision = evaluate_quality_policy(
        quality=quality,
        policy=policy,
    )

    if policy.mode != "enforce":
        return decision

    if not text or not text.strip():
        raise ExtractionQualityError(
            "empty_extraction",
            warnings=("empty_extraction", *decision.warnings),
            details={"extracted_tokens": extracted_tokens, "html_tokens": html_tokens},
        )

    if min_extracted_tokens is not None and extracted_tokens < min_extracted_tokens:
        raise ExtractionQualityError(
            "below_minimum_extracted_tokens",
            warnings=("below_minimum_extracted_tokens", *decision.warnings),
            details={
                "extracted_tokens": extracted_tokens,
                "min_extracted_tokens": min_extracted_tokens,
            },
        )

    if (
        min_yield_ratio is not None
        and html_tokens > 0
        and (extracted_tokens / html_tokens) < min_yield_ratio
    ):
        raise ExtractionQualityError(
            "low_yield_ratio",
            warnings=("low_yield_ratio", *decision.warnings),
            details={
                "extracted_tokens": extracted_tokens,
                "html_tokens": html_tokens,
                "yield_ratio": round(extracted_tokens / html_tokens, 4),
                "min_yield_ratio": min_yield_ratio,
            },
        )

    if decision.action == "reject":
        raise ExtractionQualityError(
            "quality_below_threshold",
            warnings=decision.warnings,
            details={
                "score": quality.score,
                "minimum_score": policy.minimum_score,
            },
        )

    return decision
