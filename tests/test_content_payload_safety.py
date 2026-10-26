"""HTML media-type, encoding, and payload-limit handling must fail safely."""

from __future__ import annotations

import gzip
import unittest
from unittest.mock import MagicMock

from bintu_api.scraper import (
    PayloadTooLarge,
    UnsupportedContentEncoding,
    UnsupportedMediaType,
    _read_html_response,
)


MAX_BYTES = 1024


def _response(
    body: bytes,
    content_type: str = "text/html; charset=utf-8",
    content_encoding: str = "identity",
    content_length: str | None = None,
) -> MagicMock:
    response = MagicMock()
    response.getheader.side_effect = lambda name, default=None: {
        "Content-Type": content_type,
        "Content-Encoding": content_encoding,
        "Content-Length": content_length,
    }.get(name, default)
    response.read.side_effect = [body, b""]
    return response


class ContentTypeSafetyTests(unittest.TestCase):
    def test_accepts_html(self) -> None:
        response = _response(b"<html><body>ok</body></html>")

        result = _read_html_response(response, MAX_BYTES)

        self.assertEqual(result, b"<html><body>ok</body></html>")

    def test_accepts_xhtml(self) -> None:
        response = _response(
            b"<html xmlns=\"http://www.w3.org/1999/xhtml\"><body>ok</body></html>",
            content_type="application/xhtml+xml; charset=utf-8",
        )

        result = _read_html_response(response, MAX_BYTES)

        self.assertIn(b"ok", result)

    def test_rejects_json(self) -> None:
        response = _response(
            b'{"ok": true}',
            content_type="application/json",
        )

        with self.assertRaises(UnsupportedMediaType):
            _read_html_response(response, MAX_BYTES)

    def test_rejects_plain_text(self) -> None:
        response = _response(
            b"plain text",
            content_type="text/plain",
        )

        with self.assertRaises(UnsupportedMediaType):
            _read_html_response(response, MAX_BYTES)

    def test_rejects_empty_media_type(self) -> None:
        response = _response(
            b"<html></html>",
            content_type="",
        )

        with self.assertRaises(UnsupportedMediaType):
            _read_html_response(response, MAX_BYTES)


class ContentEncodingSafetyTests(unittest.TestCase):
    def test_accepts_identity(self) -> None:
        body = b"<html><body>identity</body></html>"
        response = _response(body, content_encoding="identity")

        result = _read_html_response(response, MAX_BYTES)

        self.assertEqual(result, body)

    def test_accepts_gzip(self) -> None:
        raw = b"<html><body>compressed</body></html>"
        compressed = gzip.compress(raw)
        response = _response(
            compressed,
            content_encoding="gzip",
        )

        result = _read_html_response(response, MAX_BYTES)

        self.assertEqual(result, raw)

    def test_accepts_x_gzip(self) -> None:
        raw = b"<html><body>compressed</body></html>"
        compressed = gzip.compress(raw)
        response = _response(
            compressed,
            content_encoding="x-gzip",
        )

        result = _read_html_response(response, MAX_BYTES)

        self.assertEqual(result, raw)

    def test_rejects_brotli(self) -> None:
        response = _response(
            b"compressed-bytes",
            content_encoding="br",
        )

        with self.assertRaises(UnsupportedContentEncoding):
            _read_html_response(response, MAX_BYTES)

    def test_rejects_malformed_gzip(self) -> None:
        response = _response(
            b"not-gzip",
            content_encoding="gzip",
        )

        with self.assertRaises(UnsupportedContentEncoding):
            _read_html_response(response, MAX_BYTES)

    def test_rejects_incomplete_gzip(self) -> None:
        raw = b"<html><body>compressed</body></html>"
        compressed = gzip.compress(raw)
        truncated = compressed[:-4]
        response = _response(
            truncated,
            content_encoding="gzip",
        )

        with self.assertRaises(UnsupportedContentEncoding):
            _read_html_response(response, MAX_BYTES)

    def test_rejects_gzip_with_trailing_data(self) -> None:
        raw = b"<html><body>compressed</body></html>"
        compressed = gzip.compress(raw) + b"trailing"
        response = _response(
            compressed,
            content_encoding="gzip",
        )

        with self.assertRaises(UnsupportedContentEncoding):
            _read_html_response(response, MAX_BYTES)


class PayloadLimitSafetyTests(unittest.TestCase):
    def test_rejects_content_length_above_limit(self) -> None:
        response = _response(
            b"<html></html>",
            content_length=str(MAX_BYTES + 1),
        )

        with self.assertRaises(PayloadTooLarge):
            _read_html_response(response, MAX_BYTES)

    def test_rejects_streamed_body_above_limit(self) -> None:
        response = MagicMock()
        response.getheader.side_effect = lambda name, default=None: {
            "Content-Type": "text/html",
            "Content-Encoding": "identity",
            "Content-Length": None,
        }.get(name, default)
        response.read.side_effect = [
            b"x" * (MAX_BYTES + 1),
            b"",
        ]

        with self.assertRaises(PayloadTooLarge):
            _read_html_response(response, MAX_BYTES)

    def test_rejects_decompressed_gzip_above_limit(self) -> None:
        # A small compressed payload can expand beyond the configured limit.
        raw = b"<html>" + (b"a" * (MAX_BYTES + 1)) + b"</html>"
        compressed = gzip.compress(raw)
        response = _response(
            compressed,
            content_encoding="gzip",
        )

        with self.assertRaises(PayloadTooLarge):
            _read_html_response(response, MAX_BYTES)

    def test_accepts_body_at_exact_limit(self) -> None:
        envelope = b"<html></html>"
        body = envelope[:6] + (b"a" * (MAX_BYTES - len(envelope))) + envelope[6:]
        self.assertEqual(len(body), MAX_BYTES)

        response = _response(body)

        result = _read_html_response(response, MAX_BYTES)

        self.assertEqual(result, body)


if __name__ == "__main__":
    unittest.main(verbosity=2)