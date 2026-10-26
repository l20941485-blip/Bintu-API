"""Regression tests for IPv6 transition addresses embedding IPv4 targets.

The scraper conservatively rejects NAT64 and 6to4 addresses because their
embedded IPv4 destination can conceal loopback, private, link-local, or
metadata targets. These tests pin that boundary at both URL validation and
DNS-resolution time.
"""

import socket
import unittest
from unittest.mock import patch

from bintu_api.scraper import (
    TargetURLRejected,
    _parse_target,
    fetch_html,
)
from bintu_api.settings import Settings


def dns_result(address: str, family: int = socket.AF_INET6):
    """Build a ``socket.getaddrinfo`` record for one IPv6 address."""
    return (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 80))


class FakeResponse:
    def __init__(self):
        self.status = 200
        self.reason = "OK"
        self._headers = {"Content-Type": "text/html"}

    def getheader(self, name, default=None):
        return self._headers.get(name, default)

    def read(self, size=-1):
        return b"<p>safe</p>"


class FakeConnection:
    def __init__(self):
        self.closed = False
        self.request_args = None

    def request(self, method, path, headers):
        self.request_args = (method, path, headers)

    def getresponse(self):
        return FakeResponse()

    def close(self):
        self.closed = True


class TransitionAddressTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(api_key="", rapidapi_proxy_secret="")

    def assert_rejects_wrapped_address(self, ipv6_address):
        connection = FakeConnection()

        with (
            patch(
                "bintu_api.scraper.socket.getaddrinfo",
                return_value=[dns_result(ipv6_address)],
            ),
            patch(
                "bintu_api.scraper._make_connection",
                return_value=connection,
            ) as make_connection,
        ):
            with self.assertRaises(TargetURLRejected):
                fetch_html("http://wrapped.example/", self.settings)

        make_connection.assert_not_called()
        self.assertFalse(connection.closed)

    def test_parse_target_rejects_nat64_loopback(self):
        with self.assertRaises(TargetURLRejected):
            _parse_target(
                "http://[64:ff9b::7f00:1]/",
                settings=self.settings,
            )

    def test_parse_target_rejects_nat64_metadata(self):
        with self.assertRaises(TargetURLRejected):
            _parse_target(
                "http://[64:ff9b::a9fe:a9fe]/",
                settings=self.settings,
            )

    def test_parse_target_rejects_nat64_private_address(self):
        with self.assertRaises(TargetURLRejected):
            _parse_target(
                "http://[64:ff9b::a00:1]/",
                settings=self.settings,
            )

    def test_parse_target_rejects_6to4_loopback(self):
        with self.assertRaises(TargetURLRejected):
            _parse_target(
                "http://[2002:7f00:1::]/",
                settings=self.settings,
            )

    def test_parse_target_rejects_6to4_metadata(self):
        with self.assertRaises(TargetURLRejected):
            _parse_target(
                "http://[2002:a9fe:a9fe::]/",
                settings=self.settings,
            )

    def test_parse_target_rejects_6to4_private_address(self):
        with self.assertRaises(TargetURLRejected):
            _parse_target(
                "http://[2002:a00:1::]/",
                settings=self.settings,
            )

    def test_fetch_rejects_nat64_loopback_before_connection(self):
        self.assert_rejects_wrapped_address("64:ff9b::7f00:1")

    def test_fetch_rejects_nat64_metadata_before_connection(self):
        self.assert_rejects_wrapped_address("64:ff9b::a9fe:a9fe")

    def test_fetch_rejects_nat64_private_address_before_connection(self):
        self.assert_rejects_wrapped_address("64:ff9b::a00:1")

    def test_fetch_rejects_6to4_loopback_before_connection(self):
        self.assert_rejects_wrapped_address("2002:7f00:1::")

    def test_fetch_rejects_6to4_metadata_before_connection(self):
        self.assert_rejects_wrapped_address("2002:a9fe:a9fe::")

    def test_fetch_rejects_6to4_private_address_before_connection(self):
        self.assert_rejects_wrapped_address("2002:a00:1::")

    def test_parse_target_rejects_ipv4_translated_loopback(self):
        with self.assertRaises(TargetURLRejected):
            _parse_target(
                "http://[::ffff:0:7f00:1]/",
                settings=self.settings,
            )

    def test_parse_target_rejects_ipv4_translated_private_address(self):
        with self.assertRaises(TargetURLRejected):
            _parse_target(
                "http://[::ffff:0:0a00:1]/",
                settings=self.settings,
            )

    def test_fetch_rejects_ipv4_translated_loopback_before_connection(self):
        self.assert_rejects_wrapped_address("::ffff:0:7f00:1")

    def test_fetch_rejects_ipv4_translated_private_address_before_connection(self):
        self.assert_rejects_wrapped_address("::ffff:0:0a00:1")

if __name__ == "__main__":
    unittest.main(verbosity=2)