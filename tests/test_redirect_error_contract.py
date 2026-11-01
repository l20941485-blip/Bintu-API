from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from bintu_api.routes import _scrape_chunks
from bintu_api.scraper import RedirectedToPrivateNetwork


def _raise_redirect_to_private_network(*args, **kwargs):
    raise RedirectedToPrivateNetwork(
        "A redirect attempted to access a private network address"
    )


class RedirectErrorContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_redirect_to_private_network_has_dedicated_code(self):
        request = type("Request", (), {})()
        request.state = type("State", (), {"request_id": "test"})()
        request.app = type("App", (), {})()

        rate_limiter = MagicMock()
        rate_limiter.check = MagicMock(return_value=None)

        request.app.state = type(
            "State",
            (),
            {
                "settings": type(
                    "Settings",
                    (),
                    {"robots_mode": "off"},
                )(),
                "rate_limiter": rate_limiter,
            },
        )()

        with (
            patch(
                "bintu_api.routes._fetch_and_extract",
                new=AsyncMock(
                    side_effect=_raise_redirect_to_private_network
                ),
            ),
            self.assertRaises(HTTPException) as caught,
        ):
            await _scrape_chunks(
                request,
                "https://example.com/",
                False,
                False,
                False,
                "test-id",
                False,
                links="inline",
                skip_cache=False,
                persist=True,
                max_tokens=6000,
            )

        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(
            caught.exception.detail["code"],
            "redirect_to_private_network",
        )


if __name__ == "__main__":
    unittest.main()