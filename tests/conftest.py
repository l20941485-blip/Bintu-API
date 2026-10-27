"""Shared pytest fixtures for the Bintu API test suite."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def bypass_robots_enforcement(request):
    """Bypass robots enforcement for extraction contract tests.

    Robots enforcement has dedicated tests in
    ``tests/test_robots_route_enforcement.py``. Those tests must exercise the
    real robots decision path, so they are excluded from this bypass.

    Other extraction tests use synthetic HTML and mocked transports, and are
    focused on extraction, caching, mode, and rendering contracts rather than
    robots discovery.
    """
    if "test_robots_route_enforcement" in request.node.nodeid:
        yield
        return

    with patch(
        "bintu_api.routes._enforce_robots",
        new=AsyncMock(return_value=None),
    ):
        yield