"""Transport-level tests for robots.txt fetching.

DNS resolution and connection creation are mocked. These tests do not
perform network requests or wait for real timeouts.
"""

from __future__ import annotations

import http.client
import unittest
from unittest.mock import Mock, patch

from bintu_api import robots
from bintu_api.settings import Settings


class RobotsTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            api_key="",
            rapidapi_proxy_secret="",
        )

        self.response = Mock()
        self.response.status = 200
        self.response.getheader.return_value = None
        self.response.read.return_value = (
            b"User-agent: *\nAllow: /\n"
        )

        self.connection = Mock()
        self.connection.getresponse.return_value = self.response

        self.resolve = self.enterContext(
            patch(
                "bintu_api.robots.resolve_public_addresses",
                return_value=["93.184.216.34"],
            )
        )
        self.make_connection = self.enterContext(
            patch(
                "bintu_api.robots._make_connection",
                return_value=self.connection,
            )
        )

    def fetch(self):
        return robots._fetch_robots_text(
            "https://example.com",
            self.settings,
        )

    def test_success_passes_configured_timeout_and_closes_connection(self):
        text = self.fetch()

        self.assertEqual(
            text,
            "User-agent: *\nAllow: /\n",
        )
        self.resolve.assert_called_once_with("example.com", 443)
        self.make_connection.assert_called_once()

        args = self.make_connection.call_args.args
        self.assertEqual(args[0].scheme, "https")
        self.assertEqual(args[1], "example.com")
        self.assertEqual(args[2], "93.184.216.34")
        self.assertEqual(args[3], 443)
        self.assertEqual(args[4], robots.ROBOTS_TIMEOUT_SECONDS)
        self.assertGreater(robots.ROBOTS_TIMEOUT_SECONDS, 0)

        self.connection.request.assert_called_once()
        request_args = self.connection.request.call_args.args
        self.assertEqual(request_args, ("GET", "/robots.txt"))

        headers = self.connection.request.call_args.kwargs["headers"]
        self.assertEqual(headers["Accept-Encoding"], "identity")
        self.assertEqual(headers["Connection"], "close")
        self.assertEqual(headers["Host"], "example.com")

        self.response.read.assert_called_once_with(
            robots.MAX_ROBOTS_BYTES + 1
        )
        self.connection.close.assert_called_once()

    def test_request_timeout_is_unreachable_and_closes_connection(self):
        error = TimeoutError("request timed out")
        self.connection.request.side_effect = error

        with self.assertRaises(robots.RobotsUnreachable) as captured:
            self.fetch()

        self.assertIn("connection problem", str(captured.exception))
        self.assertIs(captured.exception.__cause__, error)
        self.connection.getresponse.assert_not_called()
        self.response.read.assert_not_called()
        self.connection.close.assert_called_once()

    def test_response_timeout_is_unreachable_and_closes_connection(self):
        error = TimeoutError("response headers timed out")
        self.connection.getresponse.side_effect = error

        with self.assertRaises(robots.RobotsUnreachable) as captured:
            self.fetch()

        self.assertIn("connection problem", str(captured.exception))
        self.assertIs(captured.exception.__cause__, error)
        self.response.read.assert_not_called()
        self.connection.close.assert_called_once()

    def test_body_timeout_is_unreachable_and_closes_connection(self):
        error = TimeoutError("body read timed out")
        self.response.read.side_effect = error

        with self.assertRaises(robots.RobotsUnreachable) as captured:
            self.fetch()

        self.assertIn("connection problem", str(captured.exception))
        self.assertIs(captured.exception.__cause__, error)
        self.response.read.assert_called_once_with(
            robots.MAX_ROBOTS_BYTES + 1
        )
        self.connection.close.assert_called_once()

    def test_connection_error_is_unreachable_and_closes_connection(self):
        error = ConnectionResetError("connection reset")
        self.connection.getresponse.side_effect = error

        with self.assertRaises(robots.RobotsUnreachable) as captured:
            self.fetch()

        self.assertIn("connection problem", str(captured.exception))
        self.assertIs(captured.exception.__cause__, error)
        self.connection.close.assert_called_once()

    def test_http_protocol_error_is_unreachable_and_closes_connection(self):
        error = http.client.RemoteDisconnected(
            "server closed without a response"
        )
        self.connection.getresponse.side_effect = error

        with self.assertRaises(robots.RobotsUnreachable) as captured:
            self.fetch()

        self.assertIn("connection problem", str(captured.exception))
        self.assertIs(captured.exception.__cause__, error)
        self.connection.close.assert_called_once()

    def test_server_error_is_unreachable_and_closes_connection(self):
        self.response.status = 503

        with self.assertRaisesRegex(
            robots.RobotsUnreachable,
            "HTTP 503",
        ):
            self.fetch()

        self.response.read.assert_not_called()
        self.connection.close.assert_called_once()

    def test_missing_robots_returns_none_and_closes_connection(self):
        self.response.status = 404

        self.assertIsNone(self.fetch())

        self.response.read.assert_not_called()
        self.connection.close.assert_called_once()

    def test_redirect_uses_timeout_on_each_connection_and_closes_both(self):
        redirect_response = Mock()
        redirect_response.status = 302
        redirect_response.getheader.side_effect = (
            lambda name: "/robots-final.txt"
            if name == "Location"
            else None
        )

        first_connection = Mock()
        first_connection.getresponse.return_value = redirect_response

        second_connection = Mock()
        second_connection.getresponse.return_value = self.response

        self.make_connection.side_effect = [
            first_connection,
            second_connection,
        ]

        text = self.fetch()

        self.assertEqual(text, "User-agent: *\nAllow: /\n")
        self.assertEqual(self.make_connection.call_count, 2)

        for call in self.make_connection.call_args_list:
            self.assertEqual(
                call.args[4],
                robots.ROBOTS_TIMEOUT_SECONDS,
            )

        self.assertEqual(
            first_connection.request.call_args.args,
            ("GET", "/robots.txt"),
        )
        self.assertEqual(
            second_connection.request.call_args.args,
            ("GET", "/robots-final.txt"),
        )

        redirect_response.read.assert_not_called()
        first_connection.close.assert_called_once()
        second_connection.close.assert_called_once()

    def test_https_downgrade_is_rejected_before_second_connection(self):
        self.response.status = 302
        self.response.getheader.side_effect = (
            lambda name: "http://example.com/robots.txt"
            if name == "Location"
            else None
        )

        with self.assertRaisesRegex(
            robots.RobotsUnreachable,
            "redirect from https to http",
        ):
            self.fetch()

        self.make_connection.assert_called_once()
        self.response.read.assert_not_called()
        self.connection.close.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)