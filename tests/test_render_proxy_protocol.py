"""CONNECT authority syntax tests; no network access."""

from __future__ import annotations

import unittest

from bintu_api.render_proxy_protocol import (
    ConnectTarget,
    ProxyRequestRejected,
    parse_connect_authority,
)


class ConnectAuthorityTests(unittest.TestCase):
    def test_valid_authorities(self) -> None:
        cases = (
            ("example.com:443", "example.com", 443),
            ("EXAMPLE.COM:443", "example.com", 443),
            ("sub-domain.example:80", "sub-domain.example", 80),
            ("1.1.1.1:443", "1.1.1.1", 443),
            ("[2606:4700::1111]:443", "2606:4700::1111", 443),
            ("example.com:65535", "example.com", 65535),
        )
        for authority, host, port in cases:
            with self.subTest(authority=authority):
                self.assertEqual(
                    parse_connect_authority(authority),
                    ConnectTarget(host=host, port=port),
                )

    def test_invalid_authorities(self) -> None:
        cases = (
            "",
            "example.com",
            "example.com:",
            "example.com:0",
            "example.com:65536",
            "example.com:-1",
            "example.com:+443",
            "https://example.com:443",
            "user@example.com:443",
            "example.com:443/path",
            "example.com:443?query",
            "example.com:443#fragment",
            " example.com:443",
            "example.com:443 ",
            "example.com:443\r\nInjected: yes",
            "example.com:\t443",
            "example.com:４４３",
            "example.com:443\x00",
            "example.com.:443",
            "-example.com:443",
            "example-.com:443",
            "example..com:443",
            "exa_mple.com:443",
            "[::1]",
            "::1:443",
            "[not-an-ip]:443",
            "[fe80::1%eth0]:443",
            ("a" * 64) + ".example:443",
            ("a" * 513) + ":443",
        )
        for authority in cases:
            with self.subTest(authority=authority):
                with self.assertRaises(ProxyRequestRejected):
                    parse_connect_authority(authority)

    def test_parsing_does_not_authorize_destination(self) -> None:
        self.assertEqual(
            parse_connect_authority("127.0.0.1:443"),
            ConnectTarget(host="127.0.0.1", port=443),
        )


if __name__ == "__main__":
    unittest.main()
