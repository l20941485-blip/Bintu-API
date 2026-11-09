"""Guardrails for the scrape service module boundary."""

from __future__ import annotations

from pathlib import Path

SERVICE_PATH = (
    Path(__file__).resolve().parents[2]
    / "bintu_api"
    / "extraction"
    / "scrape_service.py"
)


def test_scrape_service_does_not_depend_on_fastapi_request() -> None:
    source = SERVICE_PATH.read_text(encoding="utf-8")

    assert "from fastapi" not in source
    assert "request.app" not in source
    assert "request.state" not in source


def test_scrape_service_uses_request_context() -> None:
    source = SERVICE_PATH.read_text(encoding="utf-8")

    assert "from bintu_api.extraction.request_context import ScrapeRequestContext" in source
    assert "context: ScrapeRequestContext" in source
