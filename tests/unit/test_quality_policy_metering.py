import pytest

"""Quality-policy billing classification contract tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bintu_api.api.routes.extract import router
from bintu_api.extraction.models import ContentQuality
from bintu_api.observability import get_or_create_trace_id, get_stage_traces, record_stage_trace
from bintu_api.settings import Settings


def _client(*, quality_score: float):
    app = FastAPI()
    settings = Settings(
        api_key="master-secret",
        rapidapi_proxy_secret="rapidapi-secret",
    )
    app.state.settings = settings
    app.state.supabase_client = Mock()
    app.state.rate_limiter = Mock()
    app.include_router(router)

    return TestClient(app), settings


def _response(quality_score: float):
    return SimpleNamespace(
        url="https://example.com",
        text="Example content",
        truncated=False,
        cache_hit=False,
        cache_layer="none",
        approx_tokens=9,
        token_method="approx-4-chars",
        tokens=9,
        tokens_saved_estimate=0,
        low_yield=False,
        yield_hint=None,
        content_cleaning={"applied": False, "strategy": "standard"},
        content_quality=ContentQuality(
            score=quality_score,
            boilerplate_ratio=0.0,
            main_content_coverage=1.0,
            section_completeness=1.0,
        ),
        mode="scrape",
        limiting_factor="none",
    )


def _run_request(
    *,
    quality_score: float,
    quality_policy_mode: str,
    quality_minimum_score: float,
):
    client, _settings = _client(quality_score=quality_score)
    result = SimpleNamespace(
        html_tokens=100,
        limiting_factor="none",
    )
    extraction = AsyncMock(return_value=(None, result, "none", False))
    build_response = Mock(return_value=_response(quality_score))

    with (
        patch(
            "bintu_api.api.routes.extract.routes_common.fetch_and_extract",
            new=extraction,
        ),
        patch(
            "bintu_api.api.routes.extract._build_response",
            new=build_response,
        ),
        patch(
            "bintu_api.api.routes.extract.queue_usage_event"
        ) as queue_usage_event,
    ):
        response = client.get(
            "/api/v1/scrape/text",
            params={
                "url": "https://example.com",
                "quality_policy_mode": quality_policy_mode,
                "quality_minimum_score": quality_minimum_score,
            },
            headers={
                "X-API-Key": "master-secret",
                "X-RapidAPI-Proxy-Secret": "rapidapi-secret",
                "X-RapidAPI-User": "rapidapi-test-user",
            },
        )

    return response, queue_usage_event


def test_enforced_low_quality_rest_extraction_bills_zero():
    response, queue_usage_event = _run_request(
        quality_score=0.2,
        quality_policy_mode="enforce",
        quality_minimum_score=0.5,
    )

    assert response.status_code == 200

    event = queue_usage_event.call_args.args[1]
    assert event.tokens == 9
    assert event.quality_rejected is True
    assert event.billing is not None
    assert event.billing.billable_units == 0
    assert event.billing.unit == "context_tokens"


def test_warn_low_quality_rest_extraction_remains_billable():
    response, queue_usage_event = _run_request(
        quality_score=0.2,
        quality_policy_mode="warn",
        quality_minimum_score=0.5,
    )

    assert response.status_code == 200

    event = queue_usage_event.call_args.args[1]
    assert event.tokens == 9
    assert event.quality_rejected is False
    assert event.billing is not None
    assert event.billing.billable_units == 9


def test_stage_traces_correlation_and_duration():
    request_id = "req-stage-trace-check"
    expected_trace_id = get_or_create_trace_id(request_id)
    record_stage_trace(
        request_id=request_id,
        trace_id=expected_trace_id,
        stage="fetch",
        status="success",
        duration_ms=1.25,
        cache_layer="none",
    )
    record_stage_trace(
        request_id=request_id,
        trace_id=expected_trace_id,
        stage="quality_policy",
        status="rejected",
        duration_ms=-0.5,
        cache_layer="none",
        quality_score=0.2,
        tokens_returned=0,
    )
    traces = get_stage_traces(request_id)
    assert [t["stage"] for t in traces] == ["fetch", "quality_policy"]
    for trace_event in traces:
        assert trace_event["trace_id"] == expected_trace_id
        assert float(trace_event["duration_ms"]) >= 0.0
    assert traces[1]["duration_ms"] == 0.0
    assert traces[1]["status"] == "rejected"


def test_persistent_cache_hit_stage_trace_metadata():
    request_id = "req-persistent-cache-hit"
    trace_id = get_or_create_trace_id(request_id)
    record_stage_trace(
        request_id=request_id,
        trace_id=trace_id,
        stage="cache_lookup",
        status="hit",
        duration_ms=0.42,
        cache_layer="persistent",
        tokens_returned=128,
    )
    traces = get_stage_traces(request_id)
    assert len(traces) == 1
    assert traces[0]["trace_id"] == trace_id
    assert traces[0]["stage"] == "cache_lookup"
    assert traces[0]["status"] == "hit"
    assert traces[0]["cache_layer"] == "persistent"
    assert traces[0]["tokens_returned"] == 128


def test_enforce_passing_quality_remains_billable():
    response, queue_usage_event = _run_request(
        quality_score=0.8,
        quality_policy_mode="enforce",
        quality_minimum_score=0.5,
    )

    assert response.status_code == 200

    event = queue_usage_event.call_args.args[1]
    assert event.tokens == 9
    assert event.quality_rejected is False
    assert event.billing is not None
    assert event.billing.billable_units == 9

def test_slice3_stage_trace_records_cache_lookup_policy_pass_and_cache_write() -> None:
    from bintu_api.observability import get_stage_traces, record_stage_trace

    request_id = "req-slice3-trace-check"

    record_stage_trace(
        request_id=request_id,
        stage="cache_lookup",
        status="hit",
        duration_ms=1.25,
        cache_layer="memory",
        tokens_returned=120,
    )
    record_stage_trace(
        request_id=request_id,
        stage="cache_lookup",
        status="miss",
        duration_ms=0.85,
        cache_layer="none",
    )
    record_stage_trace(
        request_id=request_id,
        stage="quality_policy",
        status="passed",
        duration_ms=2.40,
        cache_layer="none",
        quality_score=0.92,
        tokens_returned=350,
    )
    record_stage_trace(
        request_id=request_id,
        stage="cache_write",
        status="success",
        duration_ms=3.10,
        cache_layer="memory",
        tokens_returned=350,
    )
    record_stage_trace(
        request_id=request_id,
        stage="cache_write",
        status="success",
        duration_ms=9.50,
        cache_layer="persistent",
        tokens_returned=350,
    )

    traces = get_stage_traces(request_id)
    assert [(item["stage"], item["status"], item["cache_layer"]) for item in traces] == [
        ("cache_lookup", "hit", "memory"),
        ("cache_lookup", "miss", "none"),
        ("quality_policy", "passed", "none"),
        ("cache_write", "success", "memory"),
        ("cache_write", "success", "persistent"),
    ]
    assert traces[2]["quality_score"] == 0.92
    assert traces[3]["tokens_returned"] == 350
    assert traces[4]["tokens_returned"] == 350

@pytest.mark.asyncio
async def test_slice4_adapter_dispatch_records_success_and_error_traces(monkeypatch) -> None:
    from types import SimpleNamespace

    from bintu_api.api import scrape_adapter
    from bintu_api.observability import get_stage_traces

    class _DummyService:
        def __init__(self, should_fail: bool = False) -> None:
            self.should_fail = should_fail

        async def fetch_and_extract(self, context, url, options):
            if self.should_fail:
                raise RuntimeError("upstream boom")
            return None, SimpleNamespace(text="ok"), "cleaned"

    dummy_request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(),
                supabase_client=None,
                cache={},
            )
        ),
        state=SimpleNamespace(request_id="req-slice4-dispatch"),
    )

    monkeypatch.setattr(
        scrape_adapter,
        "build_scrape_service",
        lambda _req: _DummyService(should_fail=False),
    )

    _, cached_ok, cleaned_ok = await scrape_adapter._fetch_and_extract(
        dummy_request,
        "https://example.com",
        include_nav=False,
        include_header=False,
        include_footer=False,
        render_js=False,
    )
    assert cached_ok.text == "ok"
    assert cleaned_ok == "cleaned"

    monkeypatch.setattr(
        scrape_adapter,
        "build_scrape_service",
        lambda _req: _DummyService(should_fail=True),
    )

    with pytest.raises(RuntimeError, match="upstream boom"):
        await scrape_adapter._fetch_and_extract(
            dummy_request,
            "https://example.com",
            include_nav=False,
            include_header=False,
            include_footer=False,
            render_js=False,
        )

    traces = get_stage_traces("req-slice4-dispatch")
    dispatch_events = [item for item in traces if item["stage"] == "adapter_dispatch"]
    assert [(item["stage"], item["status"]) for item in dispatch_events] == [
        ("adapter_dispatch", "success"),
        ("adapter_dispatch", "error"),
    ]
    assert all(item["duration_ms"] >= 0.0 for item in dispatch_events)


@pytest.mark.asyncio
async def test_slice5_chunk_route_records_chunking_and_response_delivery_traces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from bintu_api.api import scrape_adapter
    from bintu_api.api.routes import chunk as chunk_route
    from bintu_api.api.schemas import MobileScrapeTextRequest
    from bintu_api.extraction.cache_store import CachedMarkdown
    from bintu_api.observability import get_or_create_trace_id, get_stage_traces

    cached_doc = CachedMarkdown(
        markdown="# Intro\n\nFirst paragraph with details.\n\n## Details\n\nSecond section body.",
        html_tokens=40,
        tokens_saved_estimate=10,
        truncated=False,
        limiting_factor="none",
        extracted_at="2026-11-24T00:00:00+00:00",
        content_hash="abc123",
        page_title="Guide",
        content_fingerprint="fp123",
    )

    class _RateLimiter:
        def check(self, _identity: str) -> None:
            return None

    async def _fake_fetch_and_extract(*_args, **_kwargs):
        return None, cached_doc, "memory", False

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(
                    render_js_enabled=False,
                    api_key="",
                    rapidapi_proxy_secret="",
                ),
                rate_limiter=_RateLimiter(),
            )
        ),
        state=SimpleNamespace(request_id="req-slice5-chunk"),
        headers={},
        client=SimpleNamespace(host="127.0.0.1"),
    )
    payload = MobileScrapeTextRequest(url="https://example.com/guide")

    monkeypatch.setattr(chunk_route.routes_common, "verify_api_access", lambda *_a, **_kw: None)
    monkeypatch.setattr(chunk_route.routes_common, "rate_limit_identity", lambda *_a, **_kw: "anon")
    monkeypatch.setattr(scrape_adapter, "fetch_and_extract", _fake_fetch_and_extract)

    response = await chunk_route.scrape_chunks(
        request,
        payload,
        max_tokens=120,
        chunk_strategy="semantic",
    )
    assert response.chunk_count >= 1

    traces = get_stage_traces("req-slice5-chunk")
    expected_trace_id = get_or_create_trace_id("req-slice5-chunk")
    by_stage = {item["stage"]: item for item in traces}

    assert "chunking" in by_stage
    assert by_stage["chunking"]["status"] == "success"
    assert by_stage["chunking"]["trace_id"] == expected_trace_id
    assert (by_stage["chunking"]["tokens_returned"] or 0) > 0
    assert by_stage["chunking"]["duration_ms"] >= 0.0

    assert "response_delivery" in by_stage
    assert by_stage["response_delivery"]["status"] == "success"
    assert by_stage["response_delivery"]["trace_id"] == expected_trace_id
    assert by_stage["response_delivery"]["cache_layer"] == "memory"
    assert (by_stage["response_delivery"]["tokens_returned"] or 0) > 0
    assert by_stage["response_delivery"]["duration_ms"] >= 0.0

    def _boom(*_args, **_kwargs):
        raise ValueError("semantic split failure")

    monkeypatch.setattr(chunk_route, "split_semantic_chunks", _boom)
    with pytest.raises(ValueError, match="semantic split failure"):
        await chunk_route.scrape_chunks(
            request,
            payload,
            max_tokens=120,
            chunk_strategy="semantic",
        )

    err_traces = [
        item
        for item in get_stage_traces("req-slice5-chunk")
        if item["stage"] == "chunking" and item["status"] == "error"
    ]
    assert len(err_traces) == 1
    assert err_traces[0]["trace_id"] == expected_trace_id


@pytest.mark.asyncio
async def test_slice5_extract_route_records_response_delivery_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from bintu_api.api import scrape_adapter
    from bintu_api.api.routes import extract as extract_route
    from bintu_api.api.schemas import ScrapeTextResponse
    from bintu_api.extraction.cache_store import CachedMarkdown
    from bintu_api.observability import get_or_create_trace_id, get_stage_traces

    cached_doc = CachedMarkdown(
        markdown="Concise extracted text for delivery trace check.",
        html_tokens=20,
        tokens_saved_estimate=8,
        truncated=False,
        limiting_factor="none",
        extracted_at="2026-11-24T00:00:00+00:00",
        content_hash="def456",
    )

    class _RateLimiter:
        def check(self, _identity: str) -> None:
            return None

    async def _fake_fetch_and_extract(*_args, **_kwargs):
        return None, cached_doc, "persistent", False

    def _fake_build_response(url, result, _document, cache_layer, _request_id, _settings, **_kwargs):
        return ScrapeTextResponse(
            url=url,
            text=result.markdown,
            tokens=10,
            approx_tokens=10,
            html_tokens=result.html_tokens,
            tokens_saved_estimate=result.tokens_saved_estimate,
            truncated=False,
            limiting_factor="none",
            cache_hit=True,
            cache_layer=cache_layer,
            extracted_at=result.extracted_at,
        )

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(max_text_characters=6000),
                rate_limiter=_RateLimiter(),
                supabase_client=None,
            )
        ),
        state=SimpleNamespace(request_id="req-slice5-extract"),
    )

    monkeypatch.setattr(scrape_adapter, "fetch_and_extract", _fake_fetch_and_extract)
    monkeypatch.setattr(extract_route, "_build_response", _fake_build_response)

    resp = await extract_route._scrape_text(
        request,
        "https://example.com/article",
        False,
        False,
        False,
        "anon",
    )
    assert resp.approx_tokens == 10

    traces = get_stage_traces("req-slice5-extract")
    expected_trace_id = get_or_create_trace_id("req-slice5-extract")
    delivery_events = [item for item in traces if item["stage"] == "response_delivery"]
    assert len(delivery_events) == 1
    assert delivery_events[0]["status"] == "success"
    assert delivery_events[0]["trace_id"] == expected_trace_id
    assert delivery_events[0]["cache_layer"] == "persistent"
    assert delivery_events[0]["tokens_returned"] == 10
    assert delivery_events[0]["duration_ms"] >= 0.0
