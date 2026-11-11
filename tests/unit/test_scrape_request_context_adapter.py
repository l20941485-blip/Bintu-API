"""Tests for HTTP request adaptation to scrape context."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from bintu_api.api.scrape_context import build_scrape_request_context


def test_adapter_preserves_request_scoped_values():
    settings = Mock()
    database_client = Mock()
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=settings,
                supabase_client=database_client,
            )
        ),
        state=SimpleNamespace(request_id="request-id"),
    )

    context = build_scrape_request_context(request)

    assert context.settings is settings
    assert context.database_client is database_client
    assert context.request_id == "request-id"


@pytest.mark.parametrize(
    "request_state",
    [
        {},
        {"state": None},
        {"state": SimpleNamespace()},
    ],
)
def test_adapter_defaults_optional_values(request_state):
    settings = Mock()
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=settings)),
        **request_state,
    )

    context = build_scrape_request_context(request)

    assert context.settings is settings
    assert context.database_client is None
    assert context.request_id is None
