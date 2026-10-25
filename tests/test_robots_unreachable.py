"""Tests distinguishing robots denials from robots retrieval failures."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from bintu_api.robots import (
    RobotsUnreachable,
    clear_robots_cache,
    robots_decision,
)
from bintu_api.settings import Settings


class RobotsUnreachableTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_robots_cache()
        self.settings = Settings(api_key="", rapidapi_proxy_secret="")

    def test_connection_failure_is_robots_unreachable(self) -> None:
        with patch(
            "bintu_api.robots.robots_mode",
            return_value="enforce",
        ), patch(
            "bintu_api.robots._fetch_robots_text",
            side_effect=RobotsUnreachable("connection problem (TimeoutError)"),
        ):
            decision = robots_decision("https://example.com/page", self.settings)

        self.assertFalse(decision.allowed)
        self.assertTrue(decision.unreachable)
        self.assertIn("robots.txt could not be retrieved", decision.reason)

    def test_explicit_disallow_is_blocked_by_robots(self) -> None:
        with patch(
            "bintu_api.robots.robots_mode",
            return_value="enforce",
        ), patch(
            "bintu_api.robots._fetch_robots_text",
            return_value="User-agent: *\nDisallow: /private\n",
        ):
            decision = robots_decision("https://example.com/private/page", self.settings)

        self.assertFalse(decision.allowed)
        self.assertFalse(decision.unreachable)
        self.assertIn("disallowed by robots.txt", decision.reason)

    def test_allowed_page_is_allowed(self) -> None:
        with patch(
            "bintu_api.robots.robots_mode",
            return_value="enforce",
        ), patch(
            "bintu_api.robots._fetch_robots_text",
            return_value="User-agent: *\nAllow: /\n",
        ):
            decision = robots_decision("https://example.com/page", self.settings)

        self.assertTrue(decision.allowed)
        self.assertFalse(decision.unreachable)


if __name__ == "__main__":
    unittest.main(verbosity=2)
