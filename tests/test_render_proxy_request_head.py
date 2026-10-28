"""Strict CONNECT request-head tests; no network access."""

from __future__ import annotations

import unittest

from bintu_api.render_proxy_protocol import (
    MAX_CONNECT_HEAD_BYTES,
    MAX_CONNECT_LINE_BYTES,
    ConnectTarget,
    ProxyRequestRejected,
    parse_connect_request_head,
)


class ConnectRequestHeadTests(unittest.TestCase):
    def test_accepts_matching_host_and_normalizes_names(self) -> None:
        result = parse_connect_request_head(
            b"CONNECT EXAMPLE.COM:443 HTTP/1.1\r\n"
            b"Host: example.com:443\r\n"
            b"User-Agent: test-client\r\n\r\n"
        )
        self.assertEqual(result.target, ConnectTarget("example.com", 443))
        self.assertIn(("host", "example.com:443"), result.headers)

    def test_accepts_ipv6_target(self) -> None:
        result = parse_connect_request_head(
            b"CONNECT [2606:4700::1111]:443 HTTP/1.1\r\n"
            b"Host: [2606:4700::1111]:443\r\n\r\n"
        )
        self.assertEqual(
            result.target,
            ConnectTarget("2606:4700::1111", 443),
        )

    def test_rejects_malformed_or_unsupported_heads(self) -> None:
        prefix = b"CONNECT example.com:443 HTTP/1.1\r\n"
        host = b"Host: example.com:443\r\n"
        cases = (
            b"",
            prefix + host,
            b"CONNECT example.com:443 HTTP/1.1\nHost: example.com:443\n\n",
            b"GET https://example.com/ HTTP/1.1\r\n" + host + b"\r\n",
            b"CONNECT example.com:443 HTTP/1.0\r\n" + host + b"\r\n",
            b"CONNECT  example.com:443 HTTP/1.1\r\n" + host + b"\r\n",
            prefix + b"\r\n",
            prefix + b"Host: other.example:443\r\n\r\n",
            prefix + b"Host: example.com:80\r\n\r\n",
            prefix + host + b"host: example.com:443\r\n\r\n",
            prefix + b"Host : example.com:443\r\n\r\n",
            prefix + host + b" Folded: value\r\n\r\n",
            prefix + host + b"Bad Header: value\r\n\r\n",
            prefix + host + b"Missing-Colon\r\n\r\n",
            prefix + host + b"X-Test: a\tb\r\n\r\n",
            prefix + host + b"X-Test: a\x00b\r\n\r\n",
            prefix + host + b"X-Test: \xff\r\n\r\n",
            prefix + host + b"Content-Length: 0\r\n\r\n",
            prefix + host + b"Transfer-Encoding: chunked\r\n\r\n",
            prefix + host + b"Expect: 100-continue\r\n\r\n",
            prefix + host + b"Upgrade: websocket\r\n\r\n",
            prefix + host + b"\r\nextra",
            prefix + host + b"\r\nGET / HTTP/1.1\r\n\r\n",
        )
        for data in cases:
            with self.subTest(data=data):
                with self.assertRaises(ProxyRequestRejected):
                    parse_connect_request_head(data)

    def test_rejects_size_and_header_count_limits(self) -> None:
        prefix = b"CONNECT example.com:443 HTTP/1.1\r\n"
        host = b"Host: example.com:443\r\n"
        cases = (
            b"x" * (MAX_CONNECT_HEAD_BYTES + 1),
            prefix + host + b"X: " + b"a" * MAX_CONNECT_LINE_BYTES + b"\r\n\r\n",
            prefix + host + b"".join(
                f"X-{index}: value\r\n".encode("ascii")
                for index in range(64)
            ) + b"\r\n",
            prefix + host + b"".join(
                f"X-{index}: ".encode("ascii") + b"a" * 1000 + b"\r\n"
                for index in range(17)
            ) + b"\r\n",
        )
        for data in cases:
            with self.subTest(size=len(data)):
                with self.assertRaises(ProxyRequestRejected):
                    parse_connect_request_head(data)


if __name__ == "__main__":
    unittest.main()
