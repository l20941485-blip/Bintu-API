"""Route-level regression tests for robots enforcement.

These tests exercise the real robots decision and route enforcement code.
Robots.txt retrieval, page fetching, and persistent-cache access are mocked.

The client setup follows tests/test_main.py: TestClient is instantiated
without entering its lifespan context, and test dependencies are then
installed directly on application state.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient

from bintu_api.robots import (
    RobotsUnreachable,
    clear_robots_cache,
    robots_decision,
)
from bintu_api.database import CachedMarkdown
from bintu_api.settings import Settings
from main import create_app


class RobotsRouteEnforcementTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_robots_cache()
        self.addCleanup(clear_robots_cache)

    def assert_denial_before_page_fetch(
        self,
        *,
        skip_cache: bool,
        unreachable: bool,
    ) -> None:
        for render_js in (False, True):
            with self.subTest(
                skip_cache=skip_cache,
                unreachable=unreachable,
                render_js=render_js,
            ):
                clear_robots_cache()

                settings = Settings(
                    api_key="robots-route-test-key",
                    rapidapi_proxy_secret="",
                    render_js_enabled=True,
                )
                app = create_app(settings)
                client = TestClient(app)
                self.addCleanup(client.close)

                database_client = object()
                app.state.supabase_client = database_client

                memory_cache = Mock()
                memory_cache.get.return_value = None
                app.state.cache = memory_cache

                persistent_read = AsyncMock(return_value=None)
                persistent_write = AsyncMock()

                plain_fetch = Mock(
                    side_effect=AssertionError(
                        "Plain page fetch started after robots denial"
                    )
                )
                rendered_fetch = AsyncMock(
                    side_effect=AssertionError(
                        "Rendered page fetch started after robots denial"
                    )
                )

                if unreachable:
                    expected_code = "robots_unreachable"
                    expected_message = "robots.txt could not be retrieved"
                    robots_fetch = Mock(
                        side_effect=RobotsUnreachable(
                            "connection problem (TimeoutError)"
                        )
                    )
                else:
                    expected_code = "blocked_by_robots"
                    expected_message = "disallowed by robots.txt"
                    robots_fetch = Mock(
                        return_value=(
                            "User-agent: *\n"
                            "Disallow: /private/\n"
                        )
                    )

                with (
                    patch(
                        "bintu_api.routes.robots_mode",
                        return_value="enforce",
                    ),
                    patch(
                        "bintu_api.robots.robots_mode",
                        return_value="enforce",
                    ),
                    patch(
                        "bintu_api.routes.robots_decision",
                        side_effect=robots_decision,
                    ) as decision_call,
                    patch(
                        "bintu_api.robots._fetch_robots_text",
                        new=robots_fetch,
                    ),
                    patch(
                        "bintu_api.routes.get_cached_markdown",
                        new=persistent_read,
                    ),
                    patch(
                        "bintu_api.routes.upsert_cached_markdown",
                        new=persistent_write,
                    ),
                    patch(
                        "bintu_api.routes.fetch_html_document",
                        new=plain_fetch,
                    ),
                    patch(
                        "bintu_api.routes.fetch_rendered_html_document",
                        new=rendered_fetch,
                    ),
                ):
                    self.assertIs(
                        app.state.supabase_client,
                        database_client,
                    )
                    self.assertIs(app.state.cache, memory_cache)

                    response = client.get(
                        "/api/v1/scrape/text",
                        params={
                            "url": "https://example.com/private/page",
                            "skip_cache": str(skip_cache).lower(),
                            "render_js": str(render_js).lower(),
                        },
                        headers={
                            "X-API-Key": "robots-route-test-key",
                        },
                    )

                self.assertEqual(
                    response.status_code,
                    403,
                    response.text,
                )

                detail = response.json()["detail"]
                self.assertEqual(detail["code"], expected_code)
                self.assertIn(expected_message, detail["message"])

                decision_call.assert_called_once_with(
                    "https://example.com/private/page",
                    settings,
                )
                robots_fetch.assert_called_once_with(
                    "https://example.com",
                    settings,
                )

                plain_fetch.assert_not_called()
                rendered_fetch.assert_not_called()
                rendered_fetch.assert_not_awaited()

                memory_cache.set.assert_not_called()
                persistent_write.assert_not_awaited()

                if skip_cache:
                    persistent_read.assert_not_called()
                    persistent_read.assert_not_awaited()
                    memory_cache.get.assert_not_called()
                else:
                    persistent_read.assert_awaited_once_with(
                        database_client,
                        "https://example.com/private/page",
                        render_js,
                        False,
                        False,
                        False,
                    )
                    memory_cache.get.assert_called_once()

    def test_unreachable_blocks_page_fetch_on_cache_miss(self) -> None:
        self.assert_denial_before_page_fetch(
            skip_cache=False,
            unreachable=True,
        )

    def test_unreachable_blocks_page_fetch_with_skip_cache(self) -> None:
        self.assert_denial_before_page_fetch(
            skip_cache=True,
            unreachable=True,
        )

    def test_explicit_disallow_blocks_page_fetch_on_cache_miss(self) -> None:
        self.assert_denial_before_page_fetch(
            skip_cache=False,
            unreachable=False,
        )

    def test_explicit_disallow_blocks_page_fetch_with_skip_cache(self) -> None:
        self.assert_denial_before_page_fetch(
            skip_cache=True,
            unreachable=False,
        )

    def test_persistent_cache_hit_does_not_check_robots(self) -> None:
        settings = Settings(
            api_key="robots-route-test-key",
            rapidapi_proxy_secret="",
        )
        app = create_app(settings)
        client = TestClient(app)
        self.addCleanup(client.close)

        app.state.supabase_client = object()
        app.state.cache = Mock()

        cached = CachedMarkdown(
            markdown="Cached body text.",
            truncated=False,
        )

        with (
            patch(
                "bintu_api.routes.robots_decision",
            ) as decision_call,
            patch(
                "bintu_api.routes.get_cached_markdown",
                new=AsyncMock(return_value=cached),
            ),
            patch(
                "bintu_api.routes.fetch_html_document",
            ) as plain_fetch,
            patch(
                "bintu_api.routes.fetch_rendered_html_document",
            ) as rendered_fetch,
        ):
            response = client.get(
                "/api/v1/scrape/text",
                params={
                    "url": "https://example.com/cached",
                    "skip_cache": "false",
                },
                headers={
                    "X-API-Key": "robots-route-test-key",
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json()["cache_layer"],
            "persistent",
        )
        decision_call.assert_not_called()
        plain_fetch.assert_not_called()
        rendered_fetch.assert_not_called()
        rendered_fetch.assert_not_awaited()

if __name__ == "__main__":
    unittest.main(verbosity=2)