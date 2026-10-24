import asyncio
import unittest
from types import SimpleNamespace
from unittest import mock

from fastapi import HTTPException

from bintu_api import routes
from bintu_api.scraper import UpstreamHTTPError
from bintu_api.settings import Settings


class _Cache:
    def get(self, key):
        return None

    def set(self, key, value):
        pass


def _request():
    settings = Settings(api_key="", rapidapi_proxy_secret="", robots_mode="off")
    state = SimpleNamespace(
        settings=settings,
        rate_limiter=SimpleNamespace(check=lambda identity: None),
        supabase_client=None,
        cache=_Cache(),
    )
    return SimpleNamespace(app=SimpleNamespace(state=state), headers={})

def _upstream_error(status):
    error = UpstreamHTTPError.__new__(UpstreamHTTPError)
    error.status_code = status
    error.reason = "test"
    return error


class UpstreamAccessDeniedTests(unittest.TestCase):
    def _run(self, status):
        with mock.patch.object(routes, "fetch_html_document", side_effect=_upstream_error(status)):
            with self.assertRaises(HTTPException) as caught:
                asyncio.run(
                    routes._scrape_text(_request(), "https://example.com/", False, False, False, "id")
                )
        return caught.exception

    def test_denied_statuses_map_to_upstream_access_denied(self):
        for status in (401, 402, 403, 429):
            with self.subTest(status=status):
                error = self._run(status)
                self.assertEqual(error.status_code, 502)
                self.assertEqual(error.detail["code"], "upstream_access_denied")
                self.assertEqual(error.detail["upstream_status"], status)

    def test_other_statuses_stay_upstream_http_error(self):
        error = self._run(500)
        self.assertEqual(error.status_code, 502)
        self.assertEqual(error.detail["code"], "upstream_http_error")
