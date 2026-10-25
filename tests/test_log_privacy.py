"""Privacy regression tests for extraction observability.

These tests pin the guarantee that application logs may expose operational
extraction metadata, but never raw target URLs or scraped page content.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from bintu_api.observability import log_extraction_completed


class _CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(self.format(record))


@pytest.fixture()
def extraction_log_capture(monkeypatch: pytest.MonkeyPatch) -> _CaptureHandler:
    handler = _CaptureHandler()
    logger = logging.getLogger("bintu_api.extraction")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)


def test_extraction_completed_logs_hashed_url_not_raw_url(
    extraction_log_capture: _CaptureHandler,
) -> None:
    raw_url = "https://www.iana.org/domains/reserved"
    page_fragment = "IANA-managed Reserved Domains"

    log_extraction_completed(
        request_id="test-request-id",
        url=raw_url,
        mode="scrape",
        cache_hit=True,
        cache_layer="persistent",
        approx_tokens=554,
        html_tokens=2737,
        tokens_saved_estimate=2183,
        truncated=False,
        limiting_factor="none",
    )

    output = "\n".join(extraction_log_capture.records)

    assert "extraction_completed" in output
    assert "url_hash=" in output
    assert "mode=scrape" in output
    assert "cache_hit=True" in output
    assert "cache_layer=persistent" in output
    assert "approx_tokens=554" in output
    assert "html_tokens=2737" in output
    assert "tokens_saved_estimate=2183" in output
    assert "truncated=False" in output
    assert "limiting_factor=none" in output

    # Privacy guarantees: neither the target URL nor extracted content may leak.
    assert raw_url not in output
    assert page_fragment not in output


def test_extraction_completed_uses_stable_url_hash(
    extraction_log_capture: _CaptureHandler,
) -> None:
    url = "https://www.iana.org/domains/reserved"

    log_extraction_completed(
        request_id="test-request-id",
        url=url,
        mode="scrape",
        cache_hit=False,
        cache_layer="none",
        approx_tokens=10,
        html_tokens=20,
        tokens_saved_estimate=10,
        truncated=False,
        limiting_factor="none",
    )

    output = "\n".join(extraction_log_capture.records)

    assert "url_hash=a32f3bb71f3e05ea" in output