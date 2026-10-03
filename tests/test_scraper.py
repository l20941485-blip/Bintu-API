import gzip
import io
import socket
import unittest
from unittest.mock import MagicMock, patch

from bintu_api.scraper import (
    PayloadTooLarge,
    TargetURLRejected,
    TooManyRedirects,
    UnsupportedContentEncoding,
    UnsupportedMediaType,
    UpstreamHTTPError,
    _PinnedHTTPConnection,
    _read_html_response,
    fetch_html,
    fetch_html_document,
    resolve_public_addresses,
)
from bintu_api.settings import Settings


def dns_result(address: str, family: int = socket.AF_INET):
    return (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 80))


class FakeResponse:
    def __init__(self, status=200, headers=None, body=b"<p>safe</p>"):
        self.status = status
        self.reason = "OK"
        self._headers = headers or {"Content-Type": "text/html"}
        self._body = io.BytesIO(body)

    def getheader(self, name, default=None):
        return self._headers.get(name, default)

    def read(self, size=-1):
        return self._body.read(size)


class FakeConnection:
    def __init__(self, response):
        self.response = response
        self.closed = False
        self.request_args = None

    def request(self, method, path, headers):
        self.request_args = (method, path, headers)

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


class ScraperNetworkTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(api_key="", rapidapi_proxy_secret="")

    def test_resolver_rejects_private_ipv4_and_ipv6(self):
        for result in (dns_result("127.0.0.1"), dns_result("::1", socket.AF_INET6)):
            with self.subTest(address=result[4][0]), patch(
                "bintu_api.scraper.socket.getaddrinfo", return_value=[result]
            ):
                with self.assertRaises(TargetURLRejected):
                    resolve_public_addresses("target.example", 80)

    def test_private_dns_answer_is_rejected_before_connecting(self):
        with (
            patch("bintu_api.scraper.socket.getaddrinfo", return_value=[dns_result("10.0.0.7")]),
            patch("bintu_api.scraper._make_connection") as make_connection,
        ):
            with self.assertRaises(TargetURLRejected):
                fetch_html("http://target.example/", self.settings)

        make_connection.assert_not_called()

    def test_public_to_private_redirect_is_rejected_before_second_connect(self):
        redirect_response = FakeResponse(
            status=302,
            headers={"Location": "http://internal.example/admin"},
            body=b"",
        )
        connection = FakeConnection(redirect_response)
        with (
            patch(
                "bintu_api.scraper.socket.getaddrinfo",
                side_effect=[
                    [dns_result("93.184.216.34")],
                    [dns_result("192.168.1.20")],
                ],
            ),
            patch("bintu_api.scraper._make_connection", return_value=connection) as make_connection,
        ):
            with self.assertRaises(TargetURLRejected):
                fetch_html("http://public.example/", self.settings)

        make_connection.assert_called_once()
        self.assertTrue(connection.closed)

    def test_dns_changes_are_rechecked_for_each_redirect(self):
        first = FakeConnection(
            FakeResponse(status=302, headers={"Location": "http://second.example/page"}, body=b"")
        )
        second = FakeConnection(FakeResponse(body=b"<p>done</p>"))
        with (
            patch(
                "bintu_api.scraper.socket.getaddrinfo",
                side_effect=[
                    [dns_result("93.184.216.34")],
                    [dns_result("1.1.1.1")],
                ],
            ) as resolve,
            patch("bintu_api.scraper._make_connection", side_effect=[first, second]) as make_connection,
        ):
            body = fetch_html("http://first.example/", self.settings)

        self.assertEqual(body, b"<p>done</p>")
        self.assertEqual(resolve.call_count, 2)
        self.assertEqual(make_connection.call_args_list[0].args[2], "93.184.216.34")
        self.assertEqual(make_connection.call_args_list[1].args[2], "1.1.1.1")

    def test_socket_connects_to_validated_address_not_hostname(self):
        connection = _PinnedHTTPConnection("target.example", "93.184.216.34", 80, 3.0)
        fake_socket = MagicMock()
        with patch("bintu_api.scraper.socket.create_connection", return_value=fake_socket) as connect:
            connection.connect()

        connect.assert_called_once_with(("93.184.216.34", 80), 3.0, None)
        connection.close()

    def test_html_reader_is_chunk_bounded_and_stops_over_limit(self):
        response = FakeResponse(body=b"x" * 4097)
        with self.assertRaises(PayloadTooLarge):
            _read_html_response(response, 4096)

        self.assertEqual(response._body.tell(), 4097)

    def test_html_reader_rejects_non_html_before_read(self):
        response = FakeResponse(headers={"Content-Type": "application/pdf"}, body=b"%PDF")
        with self.assertRaises(UnsupportedMediaType):
            _read_html_response(response, 4096)

        self.assertEqual(response._body.tell(), 0)

    def test_html_reader_decodes_gzip_with_decoded_size_limit(self):
        body = gzip.compress(b"<p>compressed HTML</p>")
        response = FakeResponse(
            headers={"Content-Type": "text/html", "Content-Encoding": "gzip"},
            body=body,
        )

        self.assertEqual(_read_html_response(response, 4096), b"<p>compressed HTML</p>")

    def test_html_reader_rejects_gzip_expansion_over_limit(self):
        body = gzip.compress(b"x" * 4097)
        response = FakeResponse(
            headers={"Content-Type": "text/html", "Content-Encoding": "gzip"},
            body=body,
        )

        with self.assertRaises(PayloadTooLarge):
            _read_html_response(response, 4096)

    def test_html_reader_rejects_unsupported_content_encoding(self):
        response = FakeResponse(
            headers={"Content-Type": "text/html", "Content-Encoding": "br"},
            body=b"compressed",
        )

        with self.assertRaises(UnsupportedContentEncoding):
            _read_html_response(response, 4096)

    def test_redirect_limit_is_enforced(self):
        self.settings = Settings(api_key="", rapidapi_proxy_secret="")
        self.settings = self.settings.__class__(
            api_key="", rapidapi_proxy_secret="", max_redirects=1
        )
        redirect = FakeConnection(
            FakeResponse(status=302, headers={"Location": "/again"}, body=b"")
        )
        with (
            patch("bintu_api.scraper.socket.getaddrinfo", return_value=[dns_result("93.184.216.34")]),
            patch("bintu_api.scraper._make_connection", return_value=redirect),
        ):
            with self.assertRaises(TooManyRedirects):
                fetch_html("http://target.example/", self.settings)

    def test_plain_200_without_location_header_returns_body(self):
        """Regression: a 200 with no Location header must not be treated as a redirect."""
        connection = FakeConnection(
            FakeResponse(status=200, headers={"Content-Type": "text/html"}, body=b"<p>hello</p>")
        )
        with (
            patch("bintu_api.scraper.socket.getaddrinfo", return_value=[dns_result("93.184.216.34")]),
            patch("bintu_api.scraper._make_connection", return_value=connection),
        ):
            body = fetch_html("http://target.example/", self.settings)

        self.assertEqual(body, b"<p>hello</p>")
        self.assertEqual(connection.request_args[2]["Accept-Encoding"], "identity")
        self.assertTrue(connection.closed)

    def test_fetch_html_document_keeps_response_charset(self):
        response = FakeResponse(
            headers={"Content-Type": "text/html; charset=iso-8859-1"},
            body=b"<p>caf\xe9</p>",
        )
        connection = FakeConnection(response)
        with (
            patch("bintu_api.scraper.socket.getaddrinfo", return_value=[dns_result("93.184.216.34")]),
            patch("bintu_api.scraper._make_connection", return_value=connection),
        ):
            document = fetch_html_document("http://target.example/", self.settings)

        self.assertEqual(document.body, b"<p>caf\xe9</p>")
        self.assertEqual(document.charset, "iso-8859-1")

    def test_redirect_makes_exactly_two_requests_and_returns_final_body(self):
        """Regression: one Location header must trigger exactly one re-fetch."""
        first = FakeConnection(
            FakeResponse(status=302, headers={"Location": "/final"}, body=b"")
        )
        second = FakeConnection(FakeResponse(status=200, body=b"<p>final</p>"))
        with (
            patch("bintu_api.scraper.socket.getaddrinfo", return_value=[dns_result("93.184.216.34")]),
            patch("bintu_api.scraper._make_connection", side_effect=[first, second]),
        ):
            body = fetch_html("http://target.example/start", self.settings)

        self.assertEqual(body, b"<p>final</p>")
        self.assertEqual(second.request_args[1], "/final")
        self.assertTrue(first.closed)
        self.assertTrue(second.closed)

    def test_upstream_error_status_raises_upstream_http_error(self):
        connection = FakeConnection(
            FakeResponse(status=404, headers={"Content-Type": "text/html"}, body=b"")
        )
        with (
            patch("bintu_api.scraper.socket.getaddrinfo", return_value=[dns_result("93.184.216.34")]),
            patch("bintu_api.scraper._make_connection", return_value=connection),
        ):
            with self.assertRaises(UpstreamHTTPError) as raised:
                fetch_html("http://target.example/missing", self.settings)

        self.assertEqual(raised.exception.status_code, 404)

    def test_non_ascii_and_space_in_request_target_are_percent_encoded(self):
        """http.client writes the request line as latin-1, so the target must be ASCII."""
        connection = FakeConnection(FakeResponse(body=b"<p>ok</p>"))
        with (
            patch("bintu_api.scraper.socket.getaddrinfo", return_value=[dns_result("93.184.216.34")]),
            patch("bintu_api.scraper._make_connection", return_value=connection),
        ):
            fetch_html("http://target.example/café?q=a b", self.settings)

        self.assertEqual(connection.request_args[1], "/caf%C3%A9?q=a%20b")


if __name__ == "__main__":
    unittest.main(verbosity=2)