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
