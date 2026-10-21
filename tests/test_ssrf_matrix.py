"""Table-driven SSRF regression matrix for the web scraper.

Every row below is a request an attacker would try to turn Bintu into
an open proxy into the host's private network, or to smuggle a request
past the target validation layer.

The matrix is deliberately data-driven: adding a new attack vector means
adding a row, not writing a new test method. ``test_ssrf_matrix_case_count``
pins the number of rows so that accidental deletion is caught.
"""

import gzip
import io
import socket
import unittest
from unittest.mock import patch

from bintu_api.scraper import (
    PayloadTooLarge,
    TargetURLRejected,
    TooManyRedirects,
    UnsupportedContentEncoding,
    UnsupportedMediaType,
    _parse_target,
    _read_html_response,
    fetch_html,
    resolve_public_addresses,
)
from bintu_api.settings import Settings


def dns_result(address: str, family: int = socket.AF_INET):
    """Build a ``socket.getaddrinfo`` record for a single address."""
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


# --------------------------------------------------------------------------
# Matrix tables
# --------------------------------------------------------------------------

# S1/S2/S3: schemes that are not plain HTTP(S) must never reach the socket.
NON_HTTP_SCHEMES = [
    "file:///etc/passwd",
    "ftp://example.com/",
    "gopher://example.com/",
    "javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "dict://example.com:11211/",
    "ldap://example.com/",
    "jar:file:///tmp/x.jar!/",
    "netdoc://example.com/",
    "view-source:http://example.com/",
]

# S1: URLs that are not absolute http(s) URLs at all.
NOT_ABSOLUTE_URLS = [
    "",
    "   ",
    "not a url",
    "//example.com/",
    "/relative/path",
    "example.com",
    "http://",
    "https://",
]

# S2: embedded credentials must be refused (they leak to the upstream host).
CREDENTIAL_URLS = [
    "http://user:pass@example.com/",
    "http://user@example.com/",
    "http://:pass@example.com/",
    "http://user:@example.com/",
    "https://admin:secret@example.com/path",
]

# S1: control characters (CRLF injection / request smuggling).
CONTROL_CHARACTER_URLS = [
    "http://example.com/\r\nX-Injected: 1",
    "http://example.com/\nX-Injected: 1",
    "http://example.com/\tX-Injected: 1",
    "http://exa\r\nmple.com/",
]

# S1: malformed URLs that must not raise anything other than TargetURLRejected.
MALFORMED_URLS = [
    "http://example.com:65536/",
    "http://example.com:70000/",
    "http://example.com:-1/",
    "http://[::1/",
    "http://[::1",
]

# S8: ports outside 80/443 are refused by default (no host/port probe).
UNUSUAL_PORTS = [
    "http://example.com:22/",
    "http://example.com:8080/",
    "http://example.com:1/",
    "http://example.com:0/",
    "http://example.com:8443/",
    "http://example.com:65535/",
]

# S4/S5/S7: private, loopback, link-local, reserved and multicast destinations.
# These are checked at DNS-resolution time (the literal form is also covered
# by ``test_numeric_ip_literal_targets_are_rejected``).
NON_PUBLIC_ADDRESSES = [
    # IPv4 loopback / private / link-local / CGNAT / reserved
    ("127.0.0.1", socket.AF_INET),
    ("127.1.2.3", socket.AF_INET),
    ("10.0.0.1", socket.AF_INET),
    ("10.255.255.254", socket.AF_INET),
    ("172.16.0.1", socket.AF_INET),
    ("172.31.255.255", socket.AF_INET),
    ("192.168.0.1", socket.AF_INET),
    ("192.168.1.20", socket.AF_INET),
    ("169.254.169.254", socket.AF_INET),
    ("0.0.0.0", socket.AF_INET),
    ("100.64.0.1", socket.AF_INET),
    ("192.0.2.1", socket.AF_INET),
    ("198.18.0.1", socket.AF_INET),
    ("198.51.100.1", socket.AF_INET),
    ("203.0.113.1", socket.AF_INET),
    ("240.0.0.1", socket.AF_INET),
    ("255.255.255.255", socket.AF_INET),
    # IPv4 multicast
    ("224.0.0.1", socket.AF_INET),
    ("239.255.255.255", socket.AF_INET),
    # IPv6 loopback / unspecified / unique-local / link-local / docs
    ("::1", socket.AF_INET6),
    ("::", socket.AF_INET6),
    ("fc00::1", socket.AF_INET6),
    ("fd00::1", socket.AF_INET6),
    ("fe80::1", socket.AF_INET6),
    ("2001:db8::1", socket.AF_INET6),
    # IPv6 multicast
    ("ff02::1", socket.AF_INET6),
    ("ff0e::1", socket.AF_INET6),
    # IPv4-mapped IPv6 forms of the above
    ("::ffff:10.0.0.1", socket.AF_INET6),
    ("::ffff:127.0.0.1", socket.AF_INET6),
    ("::ffff:169.254.169.254", socket.AF_INET6),
    ("::ffff:224.0.0.1", socket.AF_INET6),
]

# Addresses that must keep working.
PUBLIC_ADDRESSES = [
    ("8.8.8.8", socket.AF_INET),
    ("1.1.1.1", socket.AF_INET),
    ("93.184.216.34", socket.AF_INET),
    ("2001:4860:4860::8888", socket.AF_INET6),
    ("2606:4700::1111", socket.AF_INET6),
]

# Numeric IP literals that must not be fetchable (S4). These are resolved
# through the real resolver, so they are asserted end-to-end.
NUMERIC_IP_LITERALS = [
    "127.0.0.1",
    "10.0.0.1",
    "172.16.0.1",
    "192.168.1.1",
    "169.254.169.254",
    "0.0.0.0",
    "100.64.0.1",
    "192.0.2.1",
    "198.51.100.1",
    "203.0.113.1",
    "240.0.0.1",
    "255.255.255.255",
    "224.0.0.1",
    "239.255.255.255",
    "::1",
    "fc00::1",
    "fe80::1",
    "ff02::1",
    "::ffff:10.0.0.1",
    "::ffff:224.0.0.1",
]

# Schemes/hosts that must be refused before any socket is opened.
MATRIX_CASES = (
    NON_HTTP_SCHEMES
    + NOT_ABSOLUTE_URLS
    + CREDENTIAL_URLS
    + CONTROL_CHARACTER_URLS
    + MALFORMED_URLS
    + UNUSUAL_PORTS
)


class SSRFMatrixTests(unittest.TestCase):
    """Regression matrix for the scraper's SSRF defences."""

    def setUp(self):
        self.settings = Settings(api_key="", rapidapi_proxy_secret="")

    # ------------------------------------------------------------------
    # Guard rails for the matrix itself
    # ------------------------------------------------------------------

    def test_ssrf_matrix_case_count(self):
        """Pin the matrix size so a row cannot be dropped by accident."""
        self.assertEqual(len(MATRIX_CASES), 38)
        self.assertEqual(len(NON_PUBLIC_ADDRESSES), 31)
        self.assertEqual(len(NUMERIC_IP_LITERALS), 20)

    # ------------------------------------------------------------------
    # S1: URL shape validation
    # ------------------------------------------------------------------

    def test_ssrf_matrix_url_rejections(self):
        """Every hostile URL shape is rejected at parse time."""
        for url in MATRIX_CASES:
            with self.subTest(url=url):
                with self.assertRaises(TargetURLRejected):
                    _parse_target(url, settings=self.settings)

    def test_rejection_never_leaks_unexpected_exception_types(self):
        """Hostile input must fail as TargetURLRejected, never as a crash."""
        for url in MATRIX_CASES:
            with self.subTest(url=url):
                try:
                    _parse_target(url, settings=self.settings)
                except TargetURLRejected:
                    pass
                except Exception as error:  # pragma: no cover - failure path
                    self.fail(f"{url!r} raised {type(error).__name__}: {error}")
                else:
                    self.fail(f"{url!r} was accepted but must be rejected")

    def test_credentials_are_never_forwarded_to_the_upstream(self):
        """A credential-bearing URL is refused before the request is built."""
        with self.assertRaises(TargetURLRejected):
            _parse_target("http://user:pass@example.com/", settings=self.settings)

    def test_control_characters_are_never_forwarded_to_the_upstream(self):
        """CRLF in the URL must not reach the request line."""
        with self.assertRaises(TargetURLRejected):
            _parse_target("http://example.com/\r\nX-Injected: 1", settings=self.settings)

    def test_legitimate_urls_still_parse(self):
        """The matrix must not have broken ordinary URL handling."""
        for url, expected_host, expected_port in (
            ("http://example.com/", "example.com", 80),
            ("https://example.com/", "example.com", 443),
            ("http://example.com:80/", "example.com", 80),
            ("https://example.com:443/", "example.com", 443),
            ("http://example.com/path?q=1", "example.com", 80),
        ):
            with self.subTest(url=url):
                _, host, port, _ = _parse_target(url, settings=self.settings)
                self.assertEqual((host, port), (expected_host, expected_port))

    # ------------------------------------------------------------------
    # S4/S5/S7: address validation
    # ------------------------------------------------------------------

    def test_non_public_dns_answers_are_rejected(self):
        """Private, reserved and multicast answers never become targets."""
        for address, family in NON_PUBLIC_ADDRESSES:
            with self.subTest(address=address), patch(
                "bintu_api.scraper.socket.getaddrinfo",
                return_value=[dns_result(address, family)],
            ):
                with self.assertRaises(TargetURLRejected):
                    resolve_public_addresses("target.example", 80)

    def test_public_dns_answers_are_still_accepted(self):
        """The address filter must not break legitimate public targets."""
        for address, family in PUBLIC_ADDRESSES:
            with self.subTest(address=address), patch(
                "bintu_api.scraper.socket.getaddrinfo",
                return_value=[dns_result(address, family)],
            ):
                self.assertEqual(
                    resolve_public_addresses("public.example", 80), (address,)
                )

    def test_a_single_private_answer_poisons_the_whole_resolution(self):
        """A mixed public/private answer set is rejected as a whole."""
        with patch(
            "bintu_api.scraper.socket.getaddrinfo",
            return_value=[
                dns_result("93.184.216.34"),
                dns_result("192.168.1.20"),
            ],
        ):
            with self.assertRaises(TargetURLRejected):
                resolve_public_addresses("mixed.example", 80)

    def test_numeric_ip_literal_targets_are_rejected(self):
        """A literal private IP in the URL is refused end-to-end."""
        for host in NUMERIC_IP_LITERALS:
            with self.subTest(host=host):
                with self.assertRaises(TargetURLRejected):
                    resolve_public_addresses(host, 80)

    def test_unresolvable_hostname_is_rejected(self):
        """A hostname that does not resolve is refused, not retried blindly."""
        with patch(
            "bintu_api.scraper.socket.getaddrinfo",
            side_effect=socket.gaierror("name does not resolve"),
        ):
            with self.assertRaises(TargetURLRejected):
                resolve_public_addresses("nonexistent.invalid", 80)

    # ------------------------------------------------------------------
    # S8: port allow-list
    # ------------------------------------------------------------------

    def test_unusual_ports_are_rejected_by_default(self):
        """Only 80/443 are reachable unless an operator opts in."""
        for url in UNUSUAL_PORTS:
            with self.subTest(url=url):
                with self.assertRaises(TargetURLRejected):
                    _parse_target(url, settings=self.settings)

    def test_operator_can_opt_in_to_extra_ports(self):
        """ALLOWED_PORTS widens the allow-list but nothing else."""
        settings = Settings(
            api_key="", rapidapi_proxy_secret="", allowed_ports="80,443,8080"
        )
        _, host, port, _ = _parse_target("http://example.com:8080/", settings=settings)
        self.assertEqual((host, port), ("example.com", 8080))
        with self.assertRaises(TargetURLRejected):
            _parse_target("http://example.com:22/", settings=settings)

    def test_invalid_allowed_ports_entries_are_ignored(self):
        """Garbage in ALLOWED_PORTS never widens the allow-list."""
        settings = Settings(
            api_key="", rapidapi_proxy_secret="", allowed_ports="abc,0,70000,,8080"
        )
        self.assertEqual(settings.allowed_port_set(), frozenset({80, 443, 8080}))

    def test_explicit_port_zero_is_rejected_not_defaulted(self):
        """":0" must not silently fall back to the scheme's default port."""
        with self.assertRaises(TargetURLRejected):
            _parse_target("http://example.com:0/", settings=self.settings)
        with self.assertRaises(TargetURLRejected):
            _parse_target("https://example.com:0/", settings=self.settings)

    def test_absent_port_still_uses_the_scheme_default(self):
        """A URL without a port keeps the 80/443 default."""
        _, _, http_port, _ = _parse_target("http://example.com/", settings=self.settings)
        _, _, https_port, _ = _parse_target(
            "https://example.com/", settings=self.settings
        )
        self.assertEqual((http_port, https_port), (80, 443))

    # ------------------------------------------------------------------
    # Redirects, rebinding and downgrade
    # ------------------------------------------------------------------

    def test_https_downgrade_redirect_is_refused(self):
        """S10: an https page may not hand us down to cleartext."""
        first = FakeConnection(
            FakeResponse(status=302, headers={"Location": "http://example.com/"})
        )
        with (
            patch(
                "bintu_api.scraper.socket.getaddrinfo",
                return_value=[dns_result("93.184.216.34")],
            ),
            patch("bintu_api.scraper._make_connection", return_value=first),
        ):
            with self.assertRaises(TargetURLRejected):
                fetch_html("https://example.com/", self.settings)

    def test_public_to_private_redirect_is_refused(self):
        """A redirect may not pivot the request into the private network."""
        redirect = FakeResponse(
            status=302, headers={"Location": "http://internal.example/admin"}
        )
        connection = FakeConnection(redirect)
        with (
            patch(
                "bintu_api.scraper.socket.getaddrinfo",
                side_effect=[
                    [dns_result("93.184.216.34")],
                    [dns_result("192.168.1.20")],
                ],
            ),
            patch(
                "bintu_api.scraper._make_connection", return_value=connection
            ) as make_connection,
        ):
            with self.assertRaises(TargetURLRejected):
                fetch_html("http://public.example/", self.settings)

        make_connection.assert_called_once()
        self.assertTrue(connection.closed)

    def test_dns_rebinding_is_caught_between_redirects(self):
        """Each hop resolves DNS again, so a rebound answer is refused."""
        redirect = FakeResponse(
            status=302, headers={"Location": "http://rebound.example/"}
        )
        connection = FakeConnection(redirect)
        with (
            patch(
                "bintu_api.scraper.socket.getaddrinfo",
                side_effect=[
                    [dns_result("93.184.216.34")],
                    [dns_result("127.0.0.1")],
                ],
            ),
            patch(
                "bintu_api.scraper._make_connection", return_value=connection
            ) as make_connection,
        ):
            with self.assertRaises(TargetURLRejected):
                fetch_html("http://public.example/", self.settings)

        make_connection.assert_called_once()

    def test_connection_is_pinned_to_the_validated_address(self):
        """The socket must connect to the vetted IP, not re-resolve the host."""
        captured = {}

        def capture(parsed, host, address, port, timeout):
            captured["host"] = host
            captured["address"] = address
            raise RuntimeError("stop after capturing the pinned address")

        with (
            patch(
                "bintu_api.scraper.socket.getaddrinfo",
                return_value=[dns_result("93.184.216.34")],
            ),
            patch("bintu_api.scraper._make_connection", side_effect=capture),
        ):
            with self.assertRaises(RuntimeError):
                fetch_html("http://public.example/", self.settings)

        self.assertEqual(captured["address"], "93.184.216.34")
        self.assertEqual(captured["host"], "public.example")

    def test_redirect_limit_is_enforced(self):
        """A redirect loop is stopped rather than followed forever."""
        settings = Settings(api_key="", rapidapi_proxy_secret="", max_redirects=2)
        redirect = FakeResponse(status=302, headers={"Location": "http://loop.example/"})
        connection = FakeConnection(redirect)
        with (
            patch(
                "bintu_api.scraper.socket.getaddrinfo",
                return_value=[dns_result("93.184.216.34")],
            ),
            patch(
                "bintu_api.scraper._make_connection", return_value=connection
            ) as make_connection,
        ):
            with self.assertRaises(TooManyRedirects):
                fetch_html("http://loop.example/", settings)

        self.assertEqual(make_connection.call_count, 3)

    # ------------------------------------------------------------------
    # Response size / encoding limits (resource-exhaustion guard)
    # ------------------------------------------------------------------

    def test_content_length_over_limit_is_refused(self):
        """A declared oversized body is refused before it is read."""
        response = FakeResponse(
            headers={"Content-Type": "text/html", "Content-Length": "99999999"},
            body=b"x",
        )
        with self.assertRaises(PayloadTooLarge):
            _read_html_response(response, 1024)

    def test_streamed_body_over_limit_is_refused(self):
        """A lying Content-Length cannot be used to stream past the limit."""
        response = FakeResponse(
            headers={"Content-Type": "text/html", "Content-Length": "10"},
            body=b"a" * 5000,
        )
        with self.assertRaises(PayloadTooLarge):
            _read_html_response(response, 1024)

    def test_gzip_expansion_bomb_is_refused(self):
        """A gzip bomb is refused on its decompressed size, not its wire size."""
        bomb = gzip.compress(b"a" * (8 * 1024 * 1024))
        response = FakeResponse(
            headers={"Content-Type": "text/html", "Content-Encoding": "gzip"},
            body=bomb,
        )
        with self.assertRaises(PayloadTooLarge):
            _read_html_response(response, 1024 * 1024)

    def test_gzip_within_the_limit_is_decoded(self):
        """Ordinary gzip responses must still decode correctly."""
        payload = b"<p>hello</p>"
        response = FakeResponse(
            headers={"Content-Type": "text/html", "Content-Encoding": "gzip"},
            body=gzip.compress(payload),
        )
        self.assertEqual(_read_html_response(response, 1024 * 1024), payload)

    def test_non_html_content_type_is_refused(self):
        """Only HTML/XHTML bodies are processed."""
        response = FakeResponse(
            headers={"Content-Type": "application/json"}, body=b"{}"
        )
        with self.assertRaises(UnsupportedMediaType):
            _read_html_response(response, 1024)

    def test_unsupported_content_encoding_is_refused(self):
        """Only identity/gzip bodies are processed."""
        response = FakeResponse(
            headers={"Content-Type": "text/html", "Content-Encoding": "br"}, body=b"x"
        )
        with self.assertRaises(UnsupportedContentEncoding):
            _read_html_response(response, 1024)



