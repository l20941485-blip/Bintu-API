"""Privacy regression tests for extraction failure observability."""

from __future__ import annotations

import logging

import pytest

from bintu_api.observability import log_extraction_failed


class _CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(self.format(record))


@pytest.fixture()
def failure_log_capture(monkeypatch: pytest.MonkeyPatch) -> _CaptureHandler:
    handler = _CaptureHandler()
    logger = logging.getLogger("bintu_api.extraction")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)


def test_extraction_failed_logs_hashed_url_not_raw_url(
    failure_log_capture: _CaptureHandler,
) -> None:
    raw_url = "https://www.iana.org/domains/reserved"

    log_extraction_failed(
        request_id="test-request-id",
        url=raw_url,
        mode="scrape",
        failure_code="invalid_or_unsafe_url",
        error_type="TargetURLRejected",
        duration_ms=12.34,
        status_code=None,
    )

    output = "\n".join(failure_log_capture.records)

    assert "extraction_failed" in output
    assert "url_hash=" in output
    assert "failure_code=invalid_or_unsafe_url" in output
    assert "error_type=TargetURLRejected" in output
    assert "duration_ms=12.34" in output
    assert "status_code=none" in output

    assert raw_url not in output