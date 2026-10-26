"""Redirect handling must revalidate every hop and never downgrade HTTPS."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from bintu_api.scraper import (
    FetchedHTML,
    TargetURLRejected,
    TooManyRedirects,
    UpstreamHTTPError,
    fetch_html_document,
)
from bintu_api.settings import Settings


PUBLIC_ADDRESS = "93.184.216.34"


def _redirect_response(location: str, status: int = 302) -> MagicMock:
    response = MagicMock()
    response.status = status
    response.reason = "Found"
    response.getheader.side_effect = lambda name, default=None: (
        location if name == "Location" else default
    )
    return response


def _success_response(body: bytes = b"<html><body>ok</body></html>") -> MagicMock:
    response = MagicMock()
    response.status = 200
    response.reason = "OK"
    response.getheader.side_effect = lambda name, default=None: (
        "text/html; charset=utf-8" if name == "Content-Type" else default
    )
    response.read.side_effect = [body, b""]
    return response


def _connection_for(responses: list[MagicMock]) -> MagicMock:
    connection = MagicMock()
    connection.getresponse.side_effect = responses
    return connection


class RedirectSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            api_key="",
            rapidapi_proxy_secret="",
            render_js_enabled=False,
            max_redirects=3,
        )

    def test_follows_relative_redirect_and_returns_final_url(self) -> None:
        responses = [
            _redirect_response("/final"),
            _success_response(),
        ]
        connection = _connection_for(responses)

        with patch(
            "bintu_api.scraper.resolve_public_addresses",
            return_value=(PUBLIC_ADDRESS,),
        ) as resolve, patch(
            "bintu_api.scraper._make_connection",
            return_value=connection,
        ) as make_connection:
            result = fetch_html_document(
                "https://example.com/start",
                self.settings,
            )

        self.assertIsInstance(result, FetchedHTML)
        self.assertEqual(result.final_url, "https://example.com/final")
        self.assertIn(b"ok", result.body)

        self.assertEqual(resolve.call_count, 2)
        self.assertEqual(make_connection.call_count, 2)
        self.assertEqual(
            resolve.call_args_list[0].args,
            ("example.com", 443),
        )
        self.assertEqual(
            resolve.call_args_list[1].args,
            ("example.com", 443),
        )

    def test_exceeding_redirect_limit_raises_too_many_redirects(self) -> None:
        responses = [
            _redirect_response(f"/hop-{index}")
            for index in range(self.settings.max_redirects + 1)
        ]
        connection = _connection_for(responses)

        with patch(
            "bintu_api.scraper.resolve_public_addresses",
            return_value=(PUBLIC_ADDRESS,),
        ), patch(
            "bintu_api.scraper._make_connection",
            return_value=connection,
        ):
            with self.assertRaises(TooManyRedirects):
                fetch_html_document(
                    "https://example.com/start",
                    self.settings,
                )

    def test_https_to_http_redirect_is_rejected(self) -> None:
        connection = _connection_for(
            [_redirect_response("http://example.com/insecure")]
        )

        with patch(
            "bintu_api.scraper.resolve_public_addresses",
            return_value=(PUBLIC_ADDRESS,),
        ) as resolve, patch(
            "bintu_api.scraper._make_connection",
            return_value=connection,
        ):
            with self.assertRaises(TargetURLRejected) as caught:
                fetch_html_document(
                    "https://example.com/start",
                    self.settings,
                )

        self.assertIn("HTTPS to HTTP", str(caught.exception))
        self.assertEqual(resolve.call_count, 1)

    def test_redirect_to_private_host_is_rejected(self) -> None:
        connection = _connection_for(
            [_redirect_response("https://127.0.0.1/admin")]
        )

        def resolve_by_host(host: str, port: int) -> tuple[str, ...]:
            if host == "127.0.0.1":
                raise TargetURLRejected(
                    "The target hostname resolves to a non-public address"
                )
            return (PUBLIC_ADDRESS,)

        with patch(
            "bintu_api.scraper.resolve_public_addresses",
            side_effect=resolve_by_host,
        ) as resolve, patch(
            "bintu_api.scraper._make_connection",
            return_value=connection,
        ):
            with self.assertRaises(TargetURLRejected) as caught:
                fetch_html_document(
                    "https://example.com/start",
                    self.settings,
                )

        self.assertIn("non-public address", str(caught.exception))
        self.assertEqual(resolve.call_count, 2)
        self.assertEqual(
            resolve.call_args_list[1].args,
            ("127.0.0.1", 443),
        )

    def test_redirect_to_disallowed_port_is_rejected(self) -> None:
        connection = _connection_for(
            [_redirect_response("http://example.com:8080/admin")]
        )

        with patch(
            "bintu_api.scraper.resolve_public_addresses",
            return_value=(PUBLIC_ADDRESS,),
        ) as resolve, patch(
            "bintu_api.scraper._make_connection",
            return_value=connection,
        ):
            with self.assertRaises(TargetURLRejected) as caught:
                fetch_html_document(
                    "https://example.com/start",
                    self.settings,
                )

        self.assertIn(
            "Only ports 80 and 443 are allowed by default",
            str(caught.exception),
        )
        self.assertEqual(resolve.call_count, 1)

    def test_redirect_to_ambiguous_numeric_host_is_rejected(self) -> None:
        connection = _connection_for(
            [_redirect_response("http://2130706433/admin")]
        )

        with patch(
            "bintu_api.scraper.resolve_public_addresses",
            return_value=(PUBLIC_ADDRESS,),
        ) as resolve, patch(
            "bintu_api.scraper._make_connection",
            return_value=connection,
        ):
            with self.assertRaises(TargetURLRejected) as caught:
                fetch_html_document(
                    "https://example.com/start",
                    self.settings,
                )

        self.assertIn("Ambiguous numeric host", str(caught.exception))
        self.assertEqual(resolve.call_count, 1)

    def test_each_redirect_hop_is_revalidated(self) -> None:
        responses = [
            _redirect_response("https://example.org/middle"),
            _redirect_response("https://example.net/final"),
            _success_response(),
        ]
        connection = _connection_for(responses)

        with patch(
            "bintu_api.scraper.resolve_public_addresses",
            return_value=(PUBLIC_ADDRESS,),
        ) as resolve, patch(
            "bintu_api.scraper._make_connection",
            return_value=connection,
        ):
            result = fetch_html_document(
                "https://example.com/start",
                self.settings,
            )

        self.assertEqual(result.final_url, "https://example.net/final")
        self.assertEqual(resolve.call_count, 3)
        self.assertEqual(
            [call.args[0] for call in resolve.call_args_list],
            ["example.com", "example.org", "example.net"],
        )

    def test_redirect_without_location_header_is_rejected(self) -> None:
        response = MagicMock()
        response.status = 302
        response.reason = "Found"
        response.getheader.return_value = None
        connection = _connection_for([response])

        with patch(
            "bintu_api.scraper.resolve_public_addresses",
            return_value=(PUBLIC_ADDRESS,),
        ), patch(
            "bintu_api.scraper._make_connection",
            return_value=connection,
        ):
            with self.assertRaises(UpstreamHTTPError):
                fetch_html_document(
                    "https://example.com/start",
                    self.settings,
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)