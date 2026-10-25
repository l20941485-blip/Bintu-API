"""Tests for pre-DNS rejection of ambiguous numeric URL hosts."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from bintu_api.scraper import TargetURLRejected, _parse_target
from bintu_api.settings import Settings


class AmbiguousHostTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(api_key="", rapidapi_proxy_secret="")

    def test_ambiguous_numeric_hosts_are_rejected_before_dns(self) -> None:
        urls = (
            "http://2130706433/",
            "http://02130706433/",
            "http://0x7f000001/",
            "http://0x7f.0.0.1/",
            "http://0177.0.0.1/",
            "http://127.1/",
            "http://127.0.1/",
            "http://[::ffff:127.0.0.1]/",
            "http://[64:ff9b::7f00:1]/",
            "http://[2002:7f00:1::]/",
        )

        for url in urls:
            with self.subTest(url=url):
                with patch("bintu_api.scraper.socket.getaddrinfo") as getaddrinfo:
                    with self.assertRaises(TargetURLRejected):
                        _parse_target(url, self.settings)

                getaddrinfo.assert_not_called()

    def test_canonical_public_ip_literals_are_not_ambiguous(self) -> None:
        for url, expected_host in (
            ("http://8.8.8.8/", "8.8.8.8"),
            ("http://[2001:4860:4860::8888]/", "2001:4860:4860::8888"),
        ):
            with self.subTest(url=url):
                _, host, _, _ = _parse_target(url, self.settings)
                self.assertEqual(host, expected_host)

    def test_regular_domain_names_are_not_ambiguous(self) -> None:
        _, host, _, _ = _parse_target("https://www.iana.org/domains/reserved", self.settings)
        self.assertEqual(host, "www.iana.org")


if __name__ == "__main__":
    unittest.main(verbosity=2)