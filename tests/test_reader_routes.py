from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from bintu_api.rate_limit import BurstRateLimiter
from bintu_api.reader_routes import router
from bintu_api.reader_store import SnapshotStore
from bintu_api.scraper import FetchedHTML, TargetURLRejected
from bintu_api.settings import Settings


KEY = "reader-route-test-key"
PROXY = "reader-route-test-proxy"
URL = "https://example.com/docs"
AUTH = {"X-API-Key": KEY}


@pytest.fixture
def env():
    config = Settings(
        api_key=KEY,
        rapidapi_proxy_secret=PROXY,
        require_auth=True,
        rate_limit_requests=1000,
    )
    app = FastAPI()
    app.state.settings = config
    app.state.rate_limiter = BurstRateLimiter(config)
    app.state.reader_store = SnapshotStore()
    app.state.supabase_client = None
    app.include_router(router)

    html = (
        "<main>"
        + "<p>Documentation paragraph.</p>" * 500
        + "<p>READER_END_MARKER</p></main>"
    )
    fetched = FetchedHTML(
        body=html.encode("utf-8"),
        charset="utf-8",
        final_url=URL,
    )

    with (
        patch(
            "bintu_api.routes.fetch_html_document",
            return_value=fetched,
        ) as fetch,
        patch(
            "bintu_api.routes._enforce_robots",
            new=AsyncMock(),
        ) as robots,
        TestClient(app) as client,
    ):
        yield SimpleNamespace(
            app=app, client=client, fetch=fetch, robots=robots,
        )


def initial(env, headers=None, **options):
    payload = {"url": URL, "max_tokens": 32}
    payload.update(options)
    return env.client.post(
        "/api/v1/reader/read",
        json=payload,
        headers=AUTH if headers is None else headers,
    )


def gateway(user):
    return {
        "X-RapidAPI-Proxy-Secret": PROXY,
        "X-RapidAPI-User": user,
    }


def test_long_read_reconstructs_document_with_one_fetch(env):
    response = initial(env)
    parts = []
    expected_offset = 0

    for _ in range(1000):
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["start_offset"] == expected_offset
        assert body["approx_tokens"] <= 32
        assert body["budget_scope"] == "page_text_only"
        assert "next_offset" not in body
        parts.append(body["text"])
        expected_offset = body["end_offset"]

        if not body["has_more"]:
            assert body["next_cursor"] is None
            break

        assert body["next_cursor"]
        response = env.client.post(
            "/api/v1/reader/continue",
            json={"cursor": body["next_cursor"], "max_tokens": 32},
            headers=AUTH,
        )
    else:
        pytest.fail("Continuation failed to terminate.")

    text = "".join(parts)
    assert text == (
        "\n".join(["Documentation paragraph."] * 500)
        + "\nREADER_END_MARKER"
    )
    assert len(text) > 6000
    env.fetch.assert_called_once()
    env.robots.assert_awaited_once()


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}])
def test_unauthorized_initial_read_does_not_fetch(env, headers):
    assert initial(env, headers=headers).status_code == 401
    env.fetch.assert_not_called()
    env.robots.assert_not_awaited()


def test_wrong_subscriber_cannot_continue(env):
    response = initial(env, headers=gateway("alice"))
    assert response.status_code == 200
    cursor = response.json()["next_cursor"]

    denied = env.client.post(
        "/api/v1/reader/continue",
        json={"cursor": cursor, "max_tokens": 32},
        headers=gateway("bob"),
    )
    unknown = env.client.post(
        "/api/v1/reader/continue",
        json={"cursor": "unknown", "max_tokens": 32},
        headers=gateway("bob"),
    )

    assert denied.status_code == unknown.status_code == 404
    assert denied.json() == unknown.json()
    env.fetch.assert_called_once()


def test_unauthorized_continuation_is_rejected(env):
    cursor = initial(env).json()["next_cursor"]
    response = env.client.post(
        "/api/v1/reader/continue",
        json={"cursor": cursor},
    )

    assert response.status_code == 401
    env.fetch.assert_called_once()


def test_robots_denial_prevents_page_fetch(env):
    env.robots.side_effect = HTTPException(
        status_code=403,
        detail={"code": "robots_disallowed"},
    )

    response = initial(env)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "robots_disallowed"
    env.fetch.assert_not_called()


@pytest.mark.parametrize("operation", ["initial", "continuation"])
def test_rate_limit_preserves_retry_after(env, operation):
    cursor = None
    if operation == "continuation":
        cursor = initial(env).json()["next_cursor"]
    env.fetch.reset_mock()

    env.app.state.rate_limiter = Mock()
    env.app.state.rate_limiter.check.side_effect = HTTPException(
        status_code=429,
        detail={"code": "burst_rate_limit_exceeded"},
        headers={"Retry-After": "7"},
    )

    if operation == "initial":
        response = initial(env)
    else:
        response = env.client.post(
            "/api/v1/reader/continue",
            json={"cursor": cursor},
            headers=AUTH,
        )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "7"
    env.fetch.assert_not_called()


@pytest.mark.parametrize("budget", [0, -1, 6001, True, "32", 1.5])
def test_invalid_initial_budget_does_not_fetch(env, budget):
    assert initial(env, max_tokens=budget).status_code == 422
    env.fetch.assert_not_called()


@pytest.mark.parametrize("budget", [0, 6001, True, "32"])
def test_invalid_continuation_budget_is_rejected(env, budget):
    response = env.client.post(
        "/api/v1/reader/continue",
        json={"cursor": "unknown", "max_tokens": budget},
        headers=AUTH,
    )

    assert response.status_code == 422
    env.fetch.assert_not_called()


@pytest.mark.parametrize(
    "error,status,code",
    [
        (TimeoutError("private diagnostic"), 504, "upstream_timeout"),
        (OSError("private diagnostic"), 502, "upstream_connection_error"),
        (TargetURLRejected("private diagnostic"), 400, "invalid_or_unsafe_url"),
        (RuntimeError("private diagnostic"), 500, "internal_error"),
    ],
)
def test_fetch_errors_are_mapped_without_raw_diagnostics(env, error, status, code):
    env.fetch.side_effect = error

    response = initial(env)

    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    assert "private diagnostic" not in response.text


def test_oversized_extraction_is_rejected(env):
    env.fetch.return_value = FetchedHTML(
        body=("<main>" + "x" * 200001 + "</main>").encode(),
        charset="utf-8",
        final_url=URL,
    )

    response = initial(env)

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "reader_document_too_large"


def test_empty_extraction_is_rejected(env):
    env.fetch.return_value = FetchedHTML(
        body=b"<html><body></body></html>",
        charset="utf-8",
        final_url=URL,
    )

    response = initial(env)

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "reader_document_empty"


def test_gateway_usage_counts_successful_initial_and_continuation(env):
    database = object()
    env.app.state.supabase_client = database

    with patch(
        "bintu_api.reader_routes.increment_developer_usage",
        new=AsyncMock(),
    ) as usage:
        first = initial(env, headers=gateway("alice"))
        assert first.status_code == 200
        second = env.client.post(
            "/api/v1/reader/continue",
            json={"cursor": first.json()["next_cursor"]},
            headers=gateway("alice"),
        )
        assert second.status_code == 200

        assert usage.await_count == 2
        for call in usage.await_args_list:
            assert call.args == (database, "alice")


def test_usage_failure_does_not_fail_successful_read(env):
    env.app.state.supabase_client = object()

    with patch(
        "bintu_api.reader_routes.increment_developer_usage",
        new=AsyncMock(side_effect=RuntimeError("private diagnostic")),
    ):
        response = initial(env, headers=gateway("alice"))

    assert response.status_code == 200
    assert "private diagnostic" not in response.text


def test_reader_through_real_application():
    from main import create_app

    config = Settings(
        api_key=KEY,
        rapidapi_proxy_secret=PROXY,
        require_auth=True,
        rate_limit_requests=1000,
    )
    fetched = FetchedHTML(
        body=(
            "<main>"
            + "<p>Integration paragraph.</p>" * 100
            + "</main>"
        ).encode("utf-8"),
        charset="utf-8",
        final_url=URL,
    )

    with (
        patch(
            "main.create_supabase_client",
            new=AsyncMock(return_value=None),
        ) as startup,
        patch(
            "main.create_rate_limiter",
            return_value=BurstRateLimiter(config),
        ),
        patch(
            "bintu_api.routes.fetch_html_document",
            return_value=fetched,
        ) as fetch,
        patch(
            "bintu_api.routes._enforce_robots",
            new=AsyncMock(),
        ),
    ):
        app = create_app(config)

        with TestClient(app) as client:
            paths = client.get("/openapi.json").json()["paths"]
            assert "/api/v1/reader/read" in paths
            assert "/api/v1/reader/continue" in paths

            denied = client.post(
                "/api/v1/reader/read",
                json={"url": URL, "max_tokens": 32},
            )
            assert denied.status_code == 401
            fetch.assert_not_called()

            first = client.post(
                "/api/v1/reader/read",
                json={"url": URL, "max_tokens": 32},
                headers=AUTH,
            )
            assert first.status_code == 200, first.text
            first_body = first.json()
            assert first_body["has_more"] is True
            assert first_body["next_cursor"]

            second = client.post(
                "/api/v1/reader/continue",
                json={
                    "cursor": first_body["next_cursor"],
                    "max_tokens": 32,
                },
                headers=AUTH,
            )
            assert second.status_code == 200, second.text
            assert (
                second.json()["start_offset"]
                == first_body["end_offset"]
            )

            fetch.assert_called_once()
            startup.assert_awaited_once_with(config)
