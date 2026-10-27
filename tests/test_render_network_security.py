"""Renderer preflight checks.

These tests do not establish browser connection pinning or close S9.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from bintu_api.scraper import (
    TargetURLRejected,
    fetch_rendered_html_document,
)
from bintu_api.settings import Settings


class RenderPreflightSecurityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            api_key="",
            rapidapi_proxy_secret="",
            render_js_enabled=True,
        )

    async def test_invalid_scheme_is_rejected_before_browser_start(self) -> None:
        with (
            patch(
                "bintu_api.scraper.resolve_public_addresses"
            ) as resolve,
            patch(
                "playwright.async_api.async_playwright"
            ) as start_playwright,
        ):
            with self.assertRaises(TargetURLRejected):
                await fetch_rendered_html_document(
                    "file:///etc/passwd",
                    self.settings,
                )

        resolve.assert_not_called()
        start_playwright.assert_not_called()

    async def test_rejected_dns_stops_before_browser_start(self) -> None:
        with (
            patch(
                "bintu_api.scraper.resolve_public_addresses",
                side_effect=TargetURLRejected(
                    "The target hostname resolves to a non-public address"
                ),
            ) as resolve,
            patch(
                "playwright.async_api.async_playwright"
            ) as start_playwright,
        ):
            with self.assertRaises(TargetURLRejected):
                await fetch_rendered_html_document(
                    "https://private.example/",
                    self.settings,
                )

        resolve.assert_called_once_with("private.example", 443)
        start_playwright.assert_not_called()