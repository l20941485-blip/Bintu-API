"""Bounded CONNECT head-reader tests; no network access."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from bintu_api.render_proxy import read_connect_request_head
from bintu_api.render_proxy_protocol import (
    MAX_CONNECT_HEAD_BYTES,
    ConnectTarget,
    ProxyRequestRejected,
)


HEAD = (
    b"CONNECT example.com:443 HTTP/1.1\r\n"
    b"Host: example.com:443\r\n\r\n"
)


class FakeSocket:
    def __init__(self, data=b"", *, timeout=None, error=None):
        self.data = data
        self.timeout = timeout
        self.error = error
        self.read_sizes = []
        self.timeouts = []
        self.max_chunk = 4096

    def gettimeout(self):
        return self.timeout

    def settimeout(self, timeout):
        self.timeout = timeout
        self.timeouts.append(timeout)

    def recv(self, size):
        self.read_sizes.append(size)
        if self.error is not None:
            raise self.error
        count = min(size, self.max_chunk)
        chunk, self.data = self.data[:count], self.data[count:]
        return chunk


class ConnectHeadReaderTests(unittest.TestCase):
    def read(self, client, *, timeout_seconds=5.0):
        with patch(
            "bintu_api.render_proxy.time.monotonic",
            return_value=100.0,
        ):
            return read_connect_request_head(
                client,
                timeout_seconds=timeout_seconds,
            )

    def test_reads_valid_head_and_restores_original_timeout(self):
        for original in (None, 0.0, 12.0):
            with self.subTest(original=original):
                client = FakeSocket(HEAD, timeout=original)
                head, trailing = self.read(client)
                self.assertEqual(
                    head.target,
                    ConnectTarget("example.com", 443),
                )
                self.assertEqual(trailing, b"")
                self.assertEqual(client.timeout, original)
                self.assertEqual(client.timeouts, [5.0, original])

    def test_preserves_bytes_received_after_head(self):
        tail = b"\x16\x03\x01\x00\x05hello"
        client = FakeSocket(HEAD + tail)
        head, trailing = self.read(client)
        self.assertEqual(head.target, ConnectTarget("example.com", 443))
        self.assertEqual(trailing, tail)

    def test_handles_fragmentation_including_split_terminator(self):
        for chunk_size in (1, 2, 3, 7, len(HEAD) - 1):
            with self.subTest(chunk_size=chunk_size):
                client = FakeSocket(HEAD)
                client.max_chunk = chunk_size
                head, trailing = self.read(client)
                self.assertEqual(
                    head.target,
                    ConnectTarget("example.com", 443),
                )
                self.assertEqual(trailing, b"")

    def test_unread_tail_remains_on_socket(self):
        tail = b"x" * 10000
        client = FakeSocket(HEAD + tail)
        _, trailing = self.read(client)
        self.assertEqual(trailing + client.data, tail)
        self.assertEqual(len(client.read_sizes), 1)

    def test_eof_before_complete_head_is_rejected(self):
        for data in (b"", HEAD[:-1], b"CONNECT"):
            with self.subTest(data=data):
                client = FakeSocket(data, timeout=9.0)
                with self.assertRaises(ProxyRequestRejected):
                    self.read(client)
                self.assertEqual(client.timeout, 9.0)

    def test_malformed_head_is_rejected_and_timeout_restored(self):
        client = FakeSocket(
            HEAD.replace(b"Host:", b"Other:"),
            timeout=9.0,
        )
        with self.assertRaises(ProxyRequestRejected):
            self.read(client)
        self.assertEqual(client.timeout, 9.0)

    def test_unterminated_input_is_bounded(self):
        client = FakeSocket(b"x" * (MAX_CONNECT_HEAD_BYTES + 100))
        with self.assertRaisesRegex(ProxyRequestRejected, "too large"):
            self.read(client)
        self.assertEqual(len(client.data), 100)
        self.assertEqual(sum(client.read_sizes), MAX_CONNECT_HEAD_BYTES)
        self.assertTrue(all(0 < size <= 4096 for size in client.read_sizes))
        self.assertIsNone(client.timeout)

    def test_accepts_head_at_exact_size_limit(self):
        prefix = HEAD[:-2]
        lines = b"".join(
            f"X-{index}: ".encode("ascii") + b"a" * 3990 + b"\r\n"
            for index in range(4)
        )
        padding = MAX_CONNECT_HEAD_BYTES - len(prefix + lines) - 9
        data = (
            prefix + lines + b"X-Z: " + b"a" * padding + b"\r\n\r\n"
        )
        self.assertEqual(len(data), MAX_CONNECT_HEAD_BYTES)
        client = FakeSocket(data)
        head, trailing = self.read(client)
        self.assertEqual(head.target, ConnectTarget("example.com", 443))
        self.assertEqual(trailing, b"")

    def test_rejects_head_one_byte_over_size_limit(self):
        prefix = HEAD[:-2]
        lines = b"".join(
            f"X-{index}: ".encode("ascii") + b"a" * 3990 + b"\r\n"
            for index in range(4)
        )
        padding = MAX_CONNECT_HEAD_BYTES - len(prefix + lines) - 8
        data = (
            prefix + lines + b"X-Z: " + b"a" * padding + b"\r\n\r\n"
        )
        self.assertEqual(len(data), MAX_CONNECT_HEAD_BYTES + 1)
        client = FakeSocket(data)
        with self.assertRaisesRegex(ProxyRequestRejected, "too large"):
            self.read(client)
        self.assertEqual(len(client.data), 1)

    def test_socket_timeout_becomes_request_rejection(self):
        error = TimeoutError("read timed out")
        client = FakeSocket(timeout=9.0, error=error)
        with self.assertRaises(ProxyRequestRejected) as caught:
            self.read(client)
        self.assertIs(caught.exception.__cause__, error)
        self.assertEqual(client.timeout, 9.0)

    def test_other_socket_errors_propagate_and_restore_timeout(self):
        error = ConnectionResetError("peer reset")
        client = FakeSocket(timeout=9.0, error=error)
        with self.assertRaises(ConnectionResetError) as caught:
            self.read(client)
        self.assertIs(caught.exception, error)
        self.assertEqual(client.timeout, 9.0)

    def test_invalid_timeout_does_not_touch_socket(self):
        for timeout in (0, -1, float("nan"), float("inf"), float("-inf")):
            with self.subTest(timeout=timeout):
                client = FakeSocket(HEAD, timeout=9.0)
                with self.assertRaises(ValueError):
                    self.read(client, timeout_seconds=timeout)
                self.assertEqual(client.timeouts, [])
                self.assertEqual(client.read_sizes, [])
                self.assertEqual(client.timeout, 9.0)

    def test_deadline_is_not_reset_between_reads(self):
        client = FakeSocket(HEAD, timeout=9.0)
        client.max_chunk = 1
        with patch(
            "bintu_api.render_proxy.time.monotonic",
            side_effect=[100.0, 100.0, 101.0, 102.0, 105.0],
        ):
            with self.assertRaisesRegex(
                ProxyRequestRejected,
                "deadline",
            ):
                read_connect_request_head(client, timeout_seconds=5.0)
        self.assertEqual(client.timeouts, [5.0, 3.0, 9.0])
        self.assertEqual(len(client.read_sizes), 2)

    def test_expired_deadline_prevents_first_read(self):
        client = FakeSocket(HEAD, timeout=9.0)
        with patch(
            "bintu_api.render_proxy.time.monotonic",
            side_effect=[100.0, 105.0],
        ):
            with self.assertRaises(ProxyRequestRejected):
                read_connect_request_head(client, timeout_seconds=5.0)
        self.assertEqual(client.read_sizes, [])
        self.assertEqual(client.timeout, 9.0)


if __name__ == "__main__":
    unittest.main()
