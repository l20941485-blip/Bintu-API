"""Privacy regression tests for cache observability."""

from __future__ import annotations

import logging
from collections.abc import Generator

import pytest

from bintu_api.observability import log_cache_lookup_completed


class _CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(self.format(record))


@pytest.fixture()
def cache_log_capture() -> Generator[_CaptureHandler, None, None]:
    handler = _CaptureHandler()
    logger = logging.getLogger("bintu_api.extraction")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)


def test_cache_hit_logs_hashed_url_not_raw_url(
    cache_log_capture: _CaptureHandler,
) -> None:
    raw_url = "https://www.iana.org/domains/reserved"

    log_cache_lookup_completed(
        request_id="test-request-id",
        url=raw_url,
        cache_hit=True,
        cache_layer="persistent",
        age_seconds=42.5,
    )

    output = "\n".join(cache_log_capture.records)

    assert "cache_lookup_completed" in output
    assert "url_hash=" in output
    assert "cache_hit=True" in output
    assert "cache_layer=persistent" in output
    assert "age_seconds=42.50" in output
    assert raw_url not in output


def test_cache_miss_logs_hashed_url_not_raw_url(
    cache_log_capture: _CaptureHandler,
) -> None:
    raw_url = "https://www.iana.org/domains/reserved"

    log_cache_lookup_completed(
        request_id="test-request-id",
        url=raw_url,
        cache_hit=False,
        cache_layer="none",
        age_seconds=None,
    )

    output = "\n".join(cache_log_capture.records)

    assert "cache_lookup_completed" in output
    assert "url_hash=" in output
    assert "cache_hit=False" in output
    assert "cache_layer=none" in output
    assert "age_seconds=none" in output
    assert raw_url not in output