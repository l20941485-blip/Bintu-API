"""Unit tests for rendering-proxy connection primitives."""

from __future__ import annotations

import socket
import unittest
from dataclasses import replace
from unittest.mock import MagicMock, patch

from bintu_api.render_proxy import open_validated_socket
from bintu_api.scraper import TargetURLRejected
from bintu_api.settings import Settings


class RenderProxyConnectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(api_key="", rapidapi_proxy_secret="")

    def test_invalid_scheme_does_not_create_socket(self) -> None:
        with patch("bintu_api.render_proxy.socket.socket") as factory:
            with self.assertRaises(TargetURLRejected):
                open_validated_socket("file:///etc/passwd", self.settings)

        factory.assert_not_called()

    def test_rejected_dns_does_not_create_socket(self) -> None:
        with (
            patch(
                "bintu_api.scraper.resolve_public_addresses",
                side_effect=TargetURLRejected("Non-public destination"),
            ),
            patch("bintu_api.render_proxy.socket.socket") as factory,
        ):
            with self.assertRaises(TargetURLRejected):
                open_validated_socket(
                    "https://private.example/",
                    self.settings,
                )

        factory.assert_not_called()

    def test_connect_uses_validated_ipv4_not_hostname(self) -> None:
        candidate = MagicMock()

        with (
            patch(
                "bintu_api.scraper.resolve_public_addresses",
                return_value=("93.184.216.34",),
            ) as resolve,
            patch(
                "bintu_api.render_proxy.socket.socket",
                return_value=candidate,
            ) as factory,
        ):
            result = open_validated_socket(
                "https://public.example/",
                self.settings,
            )

        resolve.assert_called_once_with("public.example", 443)
        factory.assert_called_once_with(socket.AF_INET, socket.SOCK_STREAM)
        candidate.settimeout.assert_called_once_with(
            float(self.settings.request_timeout_seconds)
        )
        candidate.connect.assert_called_once_with(("93.184.216.34", 443))
        candidate.close.assert_not_called()
        self.assertIs(result, candidate)

    def test_connect_uses_validated_ipv6(self) -> None:
        candidate = MagicMock()

        with (
            patch(
                "bintu_api.scraper.resolve_public_addresses",
                return_value=("2606:4700::1111",),
            ),
            patch(
                "bintu_api.render_proxy.socket.socket",
                return_value=candidate,
            ) as factory,
        ):
            result = open_validated_socket(
                "https://public.example/",
                self.settings,
            )

        factory.assert_called_once_with(socket.AF_INET6, socket.SOCK_STREAM)
        candidate.connect.assert_called_once_with(
            ("2606:4700::1111", 443, 0, 0)
        )
        self.assertIs(result, candidate)

    def test_failed_socket_is_closed_before_next_address(self) -> None:
        first = MagicMock()
        first.connect.side_effect = OSError("Connection failed")
        second = MagicMock()

        with (
            patch(
                "bintu_api.scraper.resolve_public_addresses",
                return_value=("93.184.216.34", "1.1.1.1"),
            ) as resolve,
            patch(
                "bintu_api.render_proxy.socket.socket",
                side_effect=[first, second],
            ),
        ):
            result = open_validated_socket(
                "https://public.example/",
                self.settings,
            )

        resolve.assert_called_once()
        first.close.assert_called_once()
        second.connect.assert_called_once_with(("1.1.1.1", 443))
        second.close.assert_not_called()
        self.assertIs(result, second)

    def test_all_failed_connections_are_closed(self) -> None:
        candidate = MagicMock()
        candidate.connect.side_effect = OSError("Connection failed")

        with (
            patch(
                "bintu_api.scraper.resolve_public_addresses",
                return_value=("93.184.216.34",),
            ),
            patch(
                "bintu_api.render_proxy.socket.socket",
                return_value=candidate,
            ),
        ):
            with self.assertRaises(OSError):
                open_validated_socket(
                    "https://public.example/",
                    self.settings,
                )

        candidate.close.assert_called_once()


    def test_invalid_timeouts_stop_before_dns_or_socket(self) -> None:
        for timeout in (0, -1, float("nan"), float("inf"), float("-inf")):
            with self.subTest(timeout=timeout):
                settings = replace(
                    self.settings,
                    request_timeout_seconds=timeout,
                )

                with (
                    patch(
                        "bintu_api.scraper.resolve_public_addresses"
                    ) as resolve,
                    patch(
                        "bintu_api.render_proxy.socket.socket"
                    ) as factory,
                ):
                    with self.assertRaises(ValueError):
                        open_validated_socket(
                            "https://public.example/",
                            settings,
                        )

                    resolve.assert_not_called()
                    factory.assert_not_called()


    def test_unexpected_setup_error_closes_socket_and_propagates(self) -> None:
        candidate = MagicMock()
        error = RuntimeError("Unexpected setup failure")
        candidate.settimeout.side_effect = error

        with (
            patch(
                "bintu_api.scraper.resolve_public_addresses",
                return_value=("93.184.216.34",),
            ),
            patch(
                "bintu_api.render_proxy.socket.socket",
                return_value=candidate,
            ),
        ):
            with self.assertRaises(RuntimeError) as raised:
                open_validated_socket(
                    "https://public.example/",
                    self.settings,
                )

        self.assertIs(raised.exception, error)
        candidate.close.assert_called_once()
        candidate.connect.assert_not_called()

    def test_failed_socket_closes_before_next_socket_is_created(self) -> None:
        first = MagicMock()
        first.connect.side_effect = OSError("Connection failed")
        second = MagicMock()
        created = []

        def make_socket(*args):
            if not created:
                created.append(first)
                return first

            first.close.assert_called_once()
            created.append(second)
            return second

        with (
            patch(
                "bintu_api.scraper.resolve_public_addresses",
                return_value=("93.184.216.34", "1.1.1.1"),
            ),
            patch(
                "bintu_api.render_proxy.socket.socket",
                side_effect=make_socket,
            ),
        ):
            result = open_validated_socket(
                "https://public.example/",
                self.settings,
            )

        self.assertEqual(len(created), 2)
        second.connect.assert_called_once_with(("1.1.1.1", 443))
        self.assertIs(result, second)


if __name__ == "__main__":
    unittest.main()
