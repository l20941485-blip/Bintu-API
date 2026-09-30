import http.client
import ipaddress
import re
import socket
import ssl
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from bintu_api.settings import Settings


READ_CHUNK_BYTES = 4096
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
USER_AGENT = "BintuAPI/1.0 (+https://rapidapi.com; public web text extraction)"


class TargetURLRejected(ValueError):
    pass


class UnsupportedMediaType(Exception):
    pass


class PayloadTooLarge(Exception):
    pass


class UpstreamHTTPError(Exception):
    def __init__(self, status_code: int, reason: str) -> None:
        self.status_code = status_code
        self.reason = reason
        super().__init__(f"Upstream returned HTTP {status_code} {reason}".strip())


class TooManyRedirects(Exception):
    pass


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, address: str, port: int, timeout: float) -> None:
        super().__init__(host, port=port, timeout=timeout)
        self._address = address

    def connect(self) -> None:
        self.sock = socket.create_connection((self._address, self.port), self.timeout, self.source_address)
        if self._tunnel_host:
            self._tunnel()


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, address: str, port: int, timeout: float) -> None:
        super().__init__(host, port=port, timeout=timeout, context=ssl.create_default_context())
        self._address = address

    def connect(self) -> None:
        raw_socket = socket.create_connection((self._address, self.port), self.timeout, self.source_address)
        if self._tunnel_host:
            self._tunnel()
        self.sock = self._context.wrap_socket(
            raw_socket,
            server_hostname=self._tunnel_host or self.host,
        )


def resolve_public_addresses(host: str, port: int) -> tuple[str, ...]:
    try:
        results = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise TargetURLRejected("The target hostname could not be resolved") from error

    addresses = tuple(dict.fromkeys(result[4][0] for result in results))
    if not addresses:
        raise TargetURLRejected("The target hostname has no addresses")

    for address in addresses:
        try:
            is_public = ipaddress.ip_address(address.split("%", 1)[0]).is_global
        except ValueError as error:
            raise TargetURLRejected("The target hostname resolved to an invalid address") from error
        if not is_public:
            raise TargetURLRejected("The target hostname resolves to a non-public address")
    return addresses


def _parse_target(url: str) -> tuple[object, str, int, str]:
    if any(character in url for character in "\r\n\t"):
        raise TargetURLRejected("The URL contains invalid characters")
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise TargetURLRejected("URL must be an absolute HTTP or HTTPS URL")
        if parsed.username is not None or parsed.password is not None:
            raise TargetURLRejected("URLs containing credentials are not allowed")
        host = parsed.hostname.encode("idna").decode("ascii")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except (UnicodeError, ValueError) as error:
        if isinstance(error, TargetURLRejected):
            raise
        raise TargetURLRejected("The target URL is malformed") from error

    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    return parsed, host, port, path


def _make_connection(parsed, host: str, address: str, port: int, timeout: float):
    connection_type = _PinnedHTTPSConnection if parsed.scheme == "https" else _PinnedHTTPConnection
    return connection_type(host, address, port, timeout)


def _host_header(host: str, port: int, scheme: str) -> str:
    formatted_host = f"[{host}]" if ":" in host else host
    default_port = 443 if scheme == "https" else 80
    return formatted_host if port == default_port else f"{formatted_host}:{port}"


def fetch_html(url: str, settings: Settings) -> bytes:
    current_url = url
    for redirect_number in range(settings.max_redirects + 1):
        parsed, host, port, path = _parse_target(current_url)
        address = resolve_public_addresses(host, port)[0]
        connection = _make_connection(parsed, host, address, port, settings.request_timeout_seconds)
        try:
            connection.request(
                "GET",
                path,
                headers={
                    "Accept": "text/html, application/xhtml+xml",
                    "Connection": "close",
                    "Host": _host_header(host, port, parsed.scheme),
                    "User-Agent": USER_AGENT,
                },
            )
            response = connection.getresponse()
            if response.status in REDIRECT_STATUSES:
                location = response.getheader("Location")
                if not location:
                    raise UpstreamHTTPError(response.status, "redirect without a Location header")
                if redirect_number >= settings.max_redirects:
                    raise TooManyRedirects("The target exceeded the redirect limit")
                current_url = urljoin(current_url, location)
                continue
            if response.status < 200 or response.status >= 300:
                raise UpstreamHTTPError(response.status, response.reason or "upstream error")
            return _read_html_response(response, settings.max_html_bytes)
        finally:
            connection.close()

    raise TooManyRedirects("The target exceeded the redirect limit")


def _read_html_response(response, max_bytes: int) -> bytes:
    content_type = response.getheader("Content-Type", "")
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type not in {"text/html", "application/xhtml+xml"}:
        raise UnsupportedMediaType("Only HTML and XHTML responses are supported")

    content_length = response.getheader("Content-Length")
    if content_length is not None:
        try:
            if int(content_length) > max_bytes:
                raise PayloadTooLarge("HTML responses may not exceed 1 MiB")
        except ValueError:
            pass

    html_bytes = bytearray()
    while True:
        remaining = max_bytes - len(html_bytes)
        chunk = response.read(min(READ_CHUNK_BYTES, remaining + 1))
        if not chunk:
            return bytes(html_bytes)
        if len(html_bytes) + len(chunk) > max_bytes:
            raise PayloadTooLarge("HTML responses may not exceed 1 MiB")
        html_bytes.extend(chunk)


def extract_text(html_bytes: bytes, max_characters: int) -> str:
    soup = BeautifulSoup(html_bytes, "html.parser")
    for node in soup(["script", "style", "header", "footer", "nav"]):
        node.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()[:max_characters]