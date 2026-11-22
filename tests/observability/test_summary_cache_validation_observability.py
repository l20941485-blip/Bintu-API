import hashlib

import pytest

from bintu_api.extraction.summary_cache import (
    SummaryCacheValidation,
    log_summary_cache_validation,
    validate_cached_extractive_summary,
)

MARKDOWN = """# Example

First useful sentence.
"""


def build_payload():
    sentence = "First useful sentence."
    start = MARKDOWN.index(sentence)

    return {
        "applied": True,
        "mode": "leading",
        "requested_sentence_count": 1,
        "returned_sentence_count": 1,
        "truncated": False,
        "algorithm_version": "v1-grounded-mmr",
        "source_fingerprint": hashlib.sha256(
            MARKDOWN.encode("utf-8")
        ).hexdigest(),
        "sentences": [
            {
                "text": sentence,
                "heading_path": ["Example"],
                "char_start": start,
                "char_end": start + len(sentence),
                "score": 1.0,
            }
        ],
    }


@pytest.mark.parametrize(
    "status",
    [
        "valid",
        "missing_metadata",
        "stale_algorithm",
        "source_changed",
        "ungrounded",
        "malformed",
    ],
)
def test_summary_cache_validation_logs_only_status(status, caplog):
    validation = SummaryCacheValidation(status=status)

    with caplog.at_level("INFO"):
        log_summary_cache_validation(validation)

    assert any(
        record.getMessage() == "cached_summary_validation"
        and record.status == status
        for record in caplog.records
    )


def test_summary_cache_validation_does_not_log_sensitive_material(caplog):
    validation = validate_cached_extractive_summary(
        MARKDOWN,
        build_payload(),
    )

    with caplog.at_level("INFO"):
        log_summary_cache_validation(validation)

    rendered = caplog.text

    assert "First useful sentence." not in rendered
    assert MARKDOWN not in rendered
    assert validation.summary_payload["source_fingerprint"] not in rendered
    assert validation.summary_payload["algorithm_version"] not in rendered
