import pytest

from bintu_api.extraction.quality import ContentQualityAssessment
from bintu_api.extraction.quality_policy import (
    QUALITY_POLICY_VERSION,
    QualityPolicy,
    evaluate_quality_policy,
)


HIGH_QUALITY = ContentQualityAssessment(
    score=0.95,
    boilerplate_ratio=0.01,
    main_content_coverage=0.95,
    section_completeness=1.0,
)

MEDIUM_QUALITY = ContentQualityAssessment(
    score=0.70,
    boilerplate_ratio=0.10,
    main_content_coverage=0.70,
    section_completeness=0.90,
)

LOW_QUALITY = ContentQualityAssessment(
    score=0.20,
    boilerplate_ratio=0.60,
    main_content_coverage=0.20,
    section_completeness=0.30,
)


def test_policy_version_is_stable():
    assert QUALITY_POLICY_VERSION == "v1"


def test_observe_always_returns_result():
    policy = QualityPolicy(mode="observe")

    decision = evaluate_quality_policy(
        quality=LOW_QUALITY,
        policy=policy,
    )

    assert decision.action == "return"
    assert decision.warnings == ()


def test_warn_returns_result_with_warning():
    policy = QualityPolicy(
        mode="warn",
        minimum_score=0.80,
    )

    decision = evaluate_quality_policy(
        quality=MEDIUM_QUALITY,
        policy=policy,
    )

    assert decision.action == "return"
    assert decision.warnings == ("quality_below_threshold",)


def test_warn_preserves_high_quality_result():
    policy = QualityPolicy(
        mode="warn",
        minimum_score=0.80,
    )

    decision = evaluate_quality_policy(
        quality=HIGH_QUALITY,
        policy=policy,
    )

    assert decision.action == "return"
    assert decision.warnings == ()


def test_enforce_rejects_low_quality_result():
    policy = QualityPolicy(
        mode="enforce",
        minimum_score=0.80,
    )

    decision = evaluate_quality_policy(
        quality=LOW_QUALITY,
        policy=policy,
    )

    assert decision.action == "reject"
    assert decision.warnings == ("quality_below_threshold",)


def test_enforce_preserves_valid_result():
    policy = QualityPolicy(
        mode="enforce",
        minimum_score=0.80,
    )

    decision = evaluate_quality_policy(
        quality=HIGH_QUALITY,
        policy=policy,
    )

    assert decision.action == "return"
    assert decision.warnings == ()


def test_policy_is_deterministic():
    policy = QualityPolicy(
        mode="warn",
        minimum_score=0.80,
    )

    first = evaluate_quality_policy(
        quality=MEDIUM_QUALITY,
        policy=policy,
    )
    second = evaluate_quality_policy(
        quality=MEDIUM_QUALITY,
        policy=policy,
    )

    assert first == second


def test_unknown_policy_mode_is_rejected():
    policy = QualityPolicy(mode="invalid")

    with pytest.raises(ValueError):
        evaluate_quality_policy(
            quality=HIGH_QUALITY,
            policy=policy,
        )
