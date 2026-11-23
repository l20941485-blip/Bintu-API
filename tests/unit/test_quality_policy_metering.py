"""Quality-policy billing classification contract tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bintu_api.api.routes.extract import router
from bintu_api.extraction.models import ContentQuality
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
