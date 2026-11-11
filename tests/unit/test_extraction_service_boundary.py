"""Tests for the request-agnostic extraction service boundary."""

from unittest.mock import AsyncMock, Mock

import pytest

from bintu_api.api import scrape_adapter as common
from bintu_api.extraction.request_context import ScrapeRequestContext
from bintu_api.extraction.scrape_options import ScrapeOptions
from bintu_api.extraction.service import (
    ScrapeDependencies,
    build_scrape_service,
    fetch_and_extract_from_context,
)


def _dependencies():
    return ScrapeDependencies(
        cache=Mock(),
        persistent_cache_reader=Mock(),
        persistent_cache_writer=AsyncMock(),
        robots_enforcer=AsyncMock(),
        html_fetcher=Mock(),
        rendered_html_fetcher=AsyncMock(),
        text_extractor=Mock(),
        source_decoder=Mock(),
        cache_event_logger=Mock(),
    )


def _context():
    return ScrapeRequestContext(
        settings=Mock(),
        database_client=None,
        request_id="request-id",
    )


def _options():
    return ScrapeOptions(
        include_nav=False,
        include_header=False,
        include_footer=False,
        render_js=False,
    )


def test_build_scrape_service_passes_all_dependencies():
    dependencies = _dependencies()

    service = build_scrape_service(dependencies)

    assert service.cache is dependencies.cache
    assert service.persistent_cache_reader is dependencies.persistent_cache_reader
    assert service.persistent_cache_writer is dependencies.persistent_cache_writer
    assert service.robots_enforcer is dependencies.robots_enforcer
    assert service.html_fetcher is dependencies.html_fetcher
    assert service.rendered_html_fetcher is dependencies.rendered_html_fetcher
    assert service.text_extractor is dependencies.text_extractor
    assert service.source_decoder is dependencies.source_decoder
    assert service.cache_event_logger is dependencies.cache_event_logger


@pytest.mark.asyncio
async def test_fetch_and_extract_from_context_uses_injected_service():
    context = _context()
    options = _options()
    service = Mock()
    service.fetch_and_extract = AsyncMock(
        return_value=(None, Mock(), "none")
    )

    result = await fetch_and_extract_from_context(
        context,
        "https://example.com",
        options,
        dependencies=_dependencies(),
        service=service,
    )

    service.fetch_and_extract.assert_awaited_once_with(
        context,
        "https://example.com",
        options,
    )
    assert result == (None, service.fetch_and_extract.return_value[1], "none")


@pytest.mark.asyncio
async def test_fetch_and_extract_from_context_builds_service():
    context = _context()
    options = _options()
    dependencies = _dependencies()

    with pytest.MonkeyPatch.context() as patcher:
        built_service = Mock()
        built_service.fetch_and_extract = AsyncMock(
            return_value=(None, Mock(), "none")
        )
        patcher.setattr(
            "bintu_api.extraction.service.build_scrape_service",
            lambda received: built_service if received is dependencies else None,
        )

        result = await fetch_and_extract_from_context(
            context,
            "https://example.com",
            options,
            dependencies=dependencies,
        )

    built_service.fetch_and_extract.assert_awaited_once_with(
        context,
        "https://example.com",
        options,
    )
    assert result == (None, built_service.fetch_and_extract.return_value[1], "none")


def test_common_fetch_and_extract_delegates_to_private_boundary():
    assert common.fetch_and_extract.__name__ == "fetch_and_extract"
    assert common._fetch_and_extract.__name__ == "_fetch_and_extract"

def test_service_boundary_has_no_route_fallback():
    import ast
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[2]
        / "bintu_api"
        / "extraction"
        / "service.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.name != "__getattr__"
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert module != "bintu_api.api"
            assert not module.startswith("bintu_api.api.")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "bintu_api.api"
                assert not alias.name.startswith("bintu_api.api.")
