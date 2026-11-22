"""Validation for extractive-summary metadata restored from a cache."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any, Literal

from bintu_api.extraction.summarizer import (
    EXTRACTIVE_SUMMARY_ALGORITHM_VERSION,
)


logger = logging.getLogger("bintu_api.scrape")


SummaryCacheStatus = Literal[
    "valid",
    "missing_metadata",
    "stale_algorithm",
    "source_changed",
    "ungrounded",
    "malformed",
]


@dataclass(frozen=True)
class SummaryCacheValidation:
    """Outcome of validating summary metadata against cached Markdown."""

    status: SummaryCacheStatus
    summary_payload: dict[str, Any] | None = None


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _has_valid_sentence_shape(sentence: Any) -> bool:
    if not isinstance(sentence, dict):
        return False

    return (
        isinstance(sentence.get("text"), str)
        and _is_non_negative_int(sentence.get("char_start"))
        and _is_non_negative_int(sentence.get("char_end"))
    )


def _is_valid_summary_payload(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False

    if not isinstance(payload.get("mode"), str):
        return False
    if not isinstance(payload.get("algorithm_version"), str):
        return False
    if not isinstance(payload.get("source_fingerprint"), str):
        return False
    if not isinstance(payload.get("truncated"), bool):
        return False
    if not _is_non_negative_int(payload.get("requested_sentence_count")):
        return False
    if not _is_non_negative_int(payload.get("returned_sentence_count")):
        return False
    if not isinstance(payload.get("sentences"), list):
        return False

    return all(
        _has_valid_sentence_shape(sentence)
        for sentence in payload["sentences"]
    )


def _is_grounded(
    markdown: str,
    sentences: list[Any],
) -> bool:
    for sentence in sentences:
        start = sentence["char_start"]
        end = sentence["char_end"]
        text = sentence["text"]

        if start > end or end > len(markdown):
            return False
        if markdown[start:end] != text:
            return False

    return True


def validate_cached_extractive_summary(
    markdown: str,
    summary_payload: dict[str, Any] | None,
) -> SummaryCacheValidation:
    """Validate summary metadata against the Markdown restored from cache.

    Missing metadata is a compatibility state, not a cache failure. Existing
    cache rows created before summary persistence remain usable.
    """
    if summary_payload is None:
        return SummaryCacheValidation(status="missing_metadata")

    if not _is_valid_summary_payload(summary_payload):
        return SummaryCacheValidation(status="malformed")

    if (
        summary_payload["algorithm_version"]
        != EXTRACTIVE_SUMMARY_ALGORITHM_VERSION
    ):
        return SummaryCacheValidation(status="stale_algorithm")

    source_fingerprint = hashlib.sha256(
        markdown.encode("utf-8")
    ).hexdigest()
    if summary_payload["source_fingerprint"] != source_fingerprint:
        return SummaryCacheValidation(status="source_changed")

    if not _is_grounded(markdown, summary_payload["sentences"]):
        return SummaryCacheValidation(status="ungrounded")

    return SummaryCacheValidation(
        status="valid",
        summary_payload=summary_payload,
    )

def log_summary_cache_validation(
    validation: SummaryCacheValidation,
) -> None:
    """Emit a privacy-safe validation outcome for a cached summary.

    The event deliberately omits URL material, Markdown, summary text,
    fingerprints, and algorithm versions.
    """
    logger.info(
        "cached_summary_validation",
        extra={"status": validation.status},
    )
