from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from bintu_api.routes import _scrape_chunks
from bintu_api.scraper import RedirectedToPrivateNetwork


class RedirectErrorContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_redirect_to_private_network_has_dedicated_code(self):
        request = type("Request", (), {})()
        request.state = type("State", (), {"request_id": "test"})()
        request.app = type("App", (), {})()

        rate_limiter = MagicMock()
        rate_limiter.check = AsyncMock(return_value=None)

        request.app.state = type(
            "State",
            (),
            {
                "settings": type(
                    "Settings",
                    (),
                    {
                        "max_text_characters": 6000,
                        "render_js_enabled": False,
                    },
                )(),
                "supabase_client": None,
                "cache": None,
                "rate_limiter": rate_limiter,
            },
        )()

        with patch(
            "bintu_api.routes._fetch_and_extract",
            new=AsyncMock(
                side_effect=RedirectedToPrivateNetwork(
                    "A redirect attempted to access a private network address"
                )
            ),
        ):
            with self.assertRaises(HTTPException) as caught:
                await _scrape_chunks(
                    request=request,
                    url="https://example.com/",
                    include_nav=False,
                    include_header=False,
                    include_footer=False,
                    identity="test",
                )

        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(
            caught.exception.detail["code"],
            "redirect_to_private_network",
        )


if __name__ == "__main__":
    unittest.main()
