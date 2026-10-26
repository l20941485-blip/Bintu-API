"""Transport-level tests for robots.txt fetching.

DNS, connection creation and monotonic time are mocked. These tests do
not perform network requests or wait for real timeouts.

They verify cooperative budget checks, not interruption of blocking DNS
or a strict wall-clock deadline inside blocking HTTP operations.
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

        self.clock = [100.0]
        self.enterContext(
            patch(
                "bintu_api.robots.time.monotonic",
                side_effect=lambda: self.clock[0],
            )
        )

        self.response = Mock()
        self.response.status = 200
        self.response.getheader.return_value = None
        self.response.read.return_value = (
            b"User-agent: *\nAllow: /\n"
        )

        self.connection = Mock()
        self.connection.sock = None
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

    def exhaust_budget(self):
        self.clock[0] += robots.ROBOTS_TIMEOUT_SECONDS + 1.0

    def test_success_passes_configured_timeout_and_closes_connection(self):
        text = self.fetch()

        self.assertEqual(text, "User-agent: *\nAllow: /\n")
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
        self.assertEqual(
            self.connection.request.call_args.args,
            ("GET", "/robots.txt"),
        )

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

    def test_redirect_shares_budget_and_closes_both_connections(self):
        redirect_response = Mock()
        redirect_response.status = 302
        redirect_response.getheader.side_effect = (
            lambda name: "/robots-final.txt"
            if name == "Location"
            else None
        )

        def first_response():
            self.clock[0] += 2.0
            return redirect_response

        first_connection = Mock()
        first_connection.sock = None
        first_connection.getresponse.side_effect = first_response

        second_connection = Mock()
        second_connection.sock = None
        second_connection.getresponse.return_value = self.response

        self.make_connection.side_effect = [
            first_connection,
            second_connection,
        ]

        text = self.fetch()

        self.assertEqual(text, "User-agent: *\nAllow: /\n")
        self.assertEqual(self.make_connection.call_count, 2)

        timeouts = [
            call.args[4]
            for call in self.make_connection.call_args_list
        ]
        self.assertEqual(
            timeouts,
            [
                robots.ROBOTS_TIMEOUT_SECONDS,
                robots.ROBOTS_TIMEOUT_SECONDS - 2.0,
            ],
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

    def test_dns_exhausting_total_budget_prevents_connection(self):
        clock = [100.0]

        def slow_resolution(host, port):
            clock[0] += robots.ROBOTS_TIMEOUT_SECONDS + 1.0
            return ["93.184.216.34"]

        self.resolve.side_effect = slow_resolution

        with patch(
            "bintu_api.robots.time.monotonic",
            side_effect=lambda: clock[0],
        ):
            with self.assertRaises(robots.RobotsUnreachable):
                self.fetch()

        self.make_connection.assert_not_called()
        self.connection.request.assert_not_called()

    def test_dns_elapsed_time_reduces_connection_timeout(self):
        def resolve(host, port):
            self.clock[0] += 3.0
            return ["93.184.216.34"]

        self.resolve.side_effect = resolve

        self.fetch()

        self.assertEqual(
            self.make_connection.call_args.args[4],
            robots.ROBOTS_TIMEOUT_SECONDS - 3.0,
        )

    def test_exact_deadline_prevents_connection(self):
        def resolve(host, port):
            self.clock[0] += robots.ROBOTS_TIMEOUT_SECONDS
            return ["93.184.216.34"]

        self.resolve.side_effect = resolve

        with self.assertRaisesRegex(
            robots.RobotsUnreachable,
            "budget exhausted",
        ):
            self.fetch()

        self.make_connection.assert_not_called()

    def test_request_exhausting_budget_prevents_response_read(self):
        self.connection.request.side_effect = (
            lambda *args, **kwargs: self.exhaust_budget()
        )

        with self.assertRaisesRegex(
            robots.RobotsUnreachable,
            "budget exhausted",
        ):
            self.fetch()

        self.connection.getresponse.assert_not_called()
        self.response.read.assert_not_called()
        self.connection.close.assert_called_once()

    def test_headers_exhausting_budget_prevents_body_read(self):
        def getresponse():
            self.exhaust_budget()
            return self.response

        self.connection.getresponse.side_effect = getresponse

        with self.assertRaisesRegex(
            robots.RobotsUnreachable,
            "budget exhausted",
        ):
            self.fetch()

        self.response.read.assert_not_called()
        self.connection.close.assert_called_once()

    def test_body_returning_after_budget_is_not_accepted(self):
        def read(size):
            self.exhaust_budget()
            return b"User-agent: *\nAllow: /\n"

        self.response.read.side_effect = read

        with self.assertRaisesRegex(
            robots.RobotsUnreachable,
            "budget exhausted",
        ):
            self.fetch()

        self.connection.close.assert_called_once()

    def test_redirect_exhausting_budget_prevents_second_connection(self):
        self.response.status = 302

        def getresponse():
            self.exhaust_budget()
            return self.response

        self.connection.getresponse.side_effect = getresponse

        with self.assertRaisesRegex(
            robots.RobotsUnreachable,
            "budget exhausted",
        ):
            self.fetch()

        self.make_connection.assert_called_once()
        self.response.read.assert_not_called()
        self.connection.close.assert_called_once()

    def test_live_socket_timeout_tracks_remaining_budget(self):
        connected_socket = Mock()

        def request(*args, **kwargs):
            self.clock[0] += 1.0
            self.connection.sock = connected_socket

        def getresponse():
            self.clock[0] += 2.0
            return self.response

        self.connection.request.side_effect = request
        self.connection.getresponse.side_effect = getresponse

        self.fetch()

        self.assertEqual(
            [
                call.args[0]
                for call in connected_socket.settimeout.call_args_list
            ],
            [
                robots.ROBOTS_TIMEOUT_SECONDS - 1.0,
                robots.ROBOTS_TIMEOUT_SECONDS - 3.0,
            ],
        )
        self.connection.close.assert_called_once()

    def test_connection_factory_error_is_unreachable(self):
        error = OSError("connection factory failed")
        self.make_connection.side_effect = error

        with self.assertRaises(robots.RobotsUnreachable) as captured:
            self.fetch()

        self.assertIs(captured.exception.__cause__, error)
        self.connection.request.assert_not_called()

    def test_budget_failure_is_preserved_as_unreachable_decision(self):
        robots.clear_robots_cache()
        self.addCleanup(robots.clear_robots_cache)

        def resolve(host, port):
            self.exhaust_budget()
            return ["93.184.216.34"]

        self.resolve.side_effect = resolve

        with patch(
            "bintu_api.robots.robots_mode",
            return_value="enforce",
        ):
            decision = robots.robots_decision(
                "https://example.com/page",
                self.settings,
            )

        self.assertFalse(decision.allowed)
        self.assertTrue(decision.unreachable)
        self.assertIn("budget exhausted", decision.reason)
        self.make_connection.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)