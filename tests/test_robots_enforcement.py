"""Robots enforcement must be mode-aware and privacy-safe."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from bintu_api.routes import _enforce_robots
from bintu_api.settings import Settings


class RobotsEnforcementTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            api_key="",
            rapidapi_proxy_secret="",
            render_js_enabled=False,
        )
        self.url = "https://example.com/private?token=secret-value"
        self.url_hash = "abc123def456"

    async def test_enforce_blocks_disallowed_url(self) -> None:
        decision = SimpleNamespace(
            allowed=False,
            unreachable=False,
            reason="Disallow: /private",
        )

        with patch(
            "bintu_api.routes.robots_mode",
            return_value="enforce",
        ), patch(
            "bintu_api.routes.robots_decision",
            new=MagicMock(return_value=decision),
        ):
            with self.assertRaises(HTTPException) as raised:
                await _enforce_robots(self.url, self.settings, self.url_hash)

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(
            raised.exception.detail["code"],
            "blocked_by_robots",
        )
        self.assertNotIn(self.url, str(raised.exception.detail))
        self.assertNotIn("secret-value", str(raised.exception.detail))

    async def test_enforce_blocks_unreachable_robots(self) -> None:
        decision = SimpleNamespace(
            allowed=False,
            unreachable=True,
            reason="robots.txt could not be retrieved",
        )

        with patch(
            "bintu_api.routes.robots_mode",
            return_value="enforce",
        ), patch(
            "bintu_api.routes.robots_decision",
            new=MagicMock(return_value=decision),
        ):
            with self.assertRaises(HTTPException) as raised:
                await _enforce_robots(self.url, self.settings, self.url_hash)

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(
            raised.exception.detail["code"],
            "robots_unreachable",
        )
        self.assertNotIn(self.url, str(raised.exception.detail))
        self.assertNotIn("secret-value", str(raised.exception.detail))

    async def test_warn_allows_disallowed_url(self) -> None:
        decision = SimpleNamespace(
            allowed=False,
            unreachable=False,
            reason="Disallow: /private",
        )

        with patch(
            "bintu_api.routes.robots_mode",
            return_value="warn",
        ), patch(
            "bintu_api.routes.robots_decision",
            new=MagicMock(return_value=decision),
        ) as robots_decision:
            await _enforce_robots(self.url, self.settings, self.url_hash)

        robots_decision.assert_called_once()

    async def test_off_skips_robots_decision(self) -> None:
        decision = SimpleNamespace(
            allowed=False,
            unreachable=False,
            reason="Disallow: /private",
        )

        with patch(
            "bintu_api.routes.robots_mode",
            return_value="off",
        ), patch(
            "bintu_api.routes.robots_decision",
            new=MagicMock(return_value=decision),
        ) as robots_decision:
            await _enforce_robots(self.url, self.settings, self.url_hash)

        robots_decision.assert_not_called()

    async def test_enforce_allows_allowed_url(self) -> None:
        decision = SimpleNamespace(
            allowed=True,
            unreachable=False,
            reason="",
        )

        with patch(
            "bintu_api.routes.robots_mode",
            return_value="enforce",
        ), patch(
            "bintu_api.routes.robots_decision",
            new=MagicMock(return_value=decision),
        ) as robots_decision:
            await _enforce_robots(self.url, self.settings, self.url_hash)

        robots_decision.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)