from bintu_api.extraction.quality import (
    assess_content_quality,
    detect_boilerplate_characters,
)


def test_clean_content_has_low_boilerplate_ratio():
    text = "# Title\n\nUseful paragraph one.\n\nUseful paragraph two."
    boilerplate = detect_boilerplate_characters(text)
    quality = assess_content_quality(
        extracted_characters=len(text),
        boilerplate_characters=boilerplate,
        pre_cleaning_characters=len(text),
        total_sections=1,
        complete_sections=1,
    )

    assert quality.boilerplate_ratio == 0.0
    assert quality.main_content_coverage == 1.0
    assert quality.section_completeness == 1.0
    assert quality.score == 1.0


def test_repeated_navigation_is_counted_as_boilerplate():
    text = "Home\nHome\nHome\nUseful article content."
    boilerplate = detect_boilerplate_characters(text)

    assert boilerplate == 12


def test_empty_content_returns_safe_defaults():
    quality = assess_content_quality(
        extracted_characters=0,
        boilerplate_characters=0,
        pre_cleaning_characters=0,
        total_sections=0,
        complete_sections=0,
    )

    assert quality.score == 0.0
    assert quality.boilerplate_ratio == 0.0
    assert quality.main_content_coverage == 0.0
    assert quality.section_completeness == 0.0


def test_section_without_body_is_incomplete():
    quality = assess_content_quality(
        extracted_characters=20,
        boilerplate_characters=0,
        pre_cleaning_characters=20,
        total_sections=2,
        complete_sections=1,
    )

    assert quality.section_completeness == 0.5


def test_metrics_are_clamped():
    quality = assess_content_quality(
        extracted_characters=10,
        boilerplate_characters=100,
        pre_cleaning_characters=5,
        total_sections=2,
        complete_sections=10,
    )

    assert 0.0 <= quality.score <= 1.0
    assert quality.boilerplate_ratio == 1.0
    assert quality.main_content_coverage == 1.0
    assert quality.section_completeness == 1.0
