"""Regression test for extractive-summary metadata persisted by ScrapeService."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from bintu_api.common.fetch import FetchedHTML
from bintu_api.extraction import scrape_service
from bintu_api.extraction.html_extract import ExtractedText
from bintu_api.extraction.scrape_service import ScrapeService
from bintu_api.extraction.summary_cache import validate_cached_extractive_summary

MARKDOWN = (
    "Bintu caches extractive summaries together with cleaned markdown.\n\n"
    "The cache validator requires a stable algorithm version and source fingerprint.\n\n"
    "Every selected sentence must remain grounded in the cached markdown offsets."
)


def test_fresh_extractive_summary_payload_is_cache_valid(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_text_extractor(*args, **kwargs):
        return ExtractedText(text=MARKDOWN, truncated=False)

    def fake_build_cached_markdown(document, extracted, url, **kwargs):
        captured["markdown"] = extracted.text
        captured["payload"] = kwargs["content_cleaning"]["extractive_summary"]
        return SimpleNamespace(markdown=extracted.text)

    async def fake_read_memory_cache(*args, **kwargs):
        return None

    async def fake_fetch_document(url, settings, cache_key, render_js):
        return (
            FetchedHTML(
                body=b"<html><body>ok</body></html>",
                charset="utf-8",
                final_url=url,
                status=200,
                redirect_count=0,
                content_type="text/html",
            ),
            object(),
        )

    monkeypatch.setattr(scrape_service, "resolve_extraction_cap", lambda settings: 200000)
    monkeypatch.setattr(scrape_service, "is_persistent_cache_enabled", lambda *a, **k: False)
    monkeypatch.setattr(scrape_service, "is_cacheable", lambda url: True)
    monkeypatch.setattr(scrape_service, "compute_cache_key", lambda **k: "cache-key")
    monkeypatch.setattr(scrape_service, "should_read_persistent_cache", lambda *a, **k: False)
    monkeypatch.setattr(scrape_service, "should_write_persistent_cache", lambda *a, **k: False)
    monkeypatch.setattr(scrape_service, "read_memory_cache", fake_read_memory_cache)
    monkeypatch.setattr(scrape_service, "write_memory_cache", lambda *a, **k: None)
    monkeypatch.setattr(scrape_service, "build_cached_markdown", fake_build_cached_markdown)

    service = ScrapeService(
        cache=object(),
        persistent_cache_reader=None,
        persistent_cache_writer=None,
        robots_enforcer=None,
        html_fetcher=None,
        rendered_html_fetcher=None,
        text_extractor=fake_text_extractor,
        source_decoder=None,
        cache_event_logger=lambda *a, **k: None,
    )
    monkeypatch.setattr(service, "_fetch_document", fake_fetch_document)

    context = SimpleNamespace(
        settings=SimpleNamespace(cache_ttl_seconds=300),
        database_client=None,
        request_id="test-request",
    )
    options = SimpleNamespace(
        include_nav=False,
        include_header=False,
        include_footer=False,
        render_js=False,
        links="inline",
        skip_cache=False,
        persist=True,
        mode="scrape",
        max_tokens=6000,
        footnote_url_policy="truncated",
        max_footnote_url_length=100,
        sections=None,
        main_content_only=False,
        exclude_terminal_sections=False,
        summary_mode="key_sentences",
        summary_sentence_count=2,
    )

    asyncio.run(service.fetch_and_extract(context, "https://example.com/article", options))

    markdown = captured["markdown"]
    payload = captured["payload"]
    assert isinstance(markdown, str)
    assert isinstance(payload, dict)
    assert payload.get("algorithm_version")
    assert payload.get("source_fingerprint")

    validation = validate_cached_extractive_summary(markdown, payload)
    assert validation.status == "valid"
