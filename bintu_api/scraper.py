"""Web fetching for Bintu.

This module owns network fetching, safety checks, and HTML retrieval without
making metering or HTTP route decisions. Text extraction lives in
``bintu_api.extraction.html_extract``.
"""

from __future__ import annotations

import asyncio
import codecs
import http.client
import ipaddress
import logging
import math
import re
import socket
import ssl
import zlib
from dataclasses import dataclass
from email.message import Message
from urllib.parse import quote, urljoin, urlsplit

from bintu_api.extraction.html_extract import (
    ExtractedText,
    extract_text,
    extract_text_result,
)
from bintu_api.settings import Settings

logger = logging.getLogger(__name__)
READ_CHUNK_BYTES = 4096
REDIRECT_STATUSES = {301, 302, 303, 307, 308}


def get_user_agent(settings) -> str:
    """Build the honest, identifiable User-Agent: BintuBot/<version> (+<info url>; <contact>)."""
    version = (getattr(settings, "service_version", "") or "").strip() or "0"
    details = []
    info_url = (getattr(settings, "bot_info_url", "") or "").strip()
    contact = (getattr(settings, "contact_email", "") or "").strip()
    if info_url:
        details.append(f"+{info_url}")
    if contact:
        details.append(contact)
    suffix = f" ({'; '.join(details)})" if details else ""
    return f"BintuBot/{version}{suffix}"


@dataclass(frozen=True)
class FetchedHTML:
    body: bytes
    charset: str | None
    final_url: str | None = None


def _compute_approx_tokens(text: str) -> int:
    """Approximate token count: ceil(characters / 4). An estimate, not a tokenizer count."""
    if not text or not text.strip():
        return 0
    return math.ceil(len(text) / 4)


def _compute_tokens_saved_estimate(
    raw_html_bytes: bytes,
    extracted_text: str,
) -> int:
    """Approximate tokens of fetched HTML minus approximate tokens of returned text, floored at 0."""
    html_text = raw_html_bytes.decode("utf-8", errors="replace")
    return max(
        0,
        _compute_approx_tokens(html_text) - _compute_approx_tokens(extracted_text),
    )


class TargetURLRejected(ValueError):
    pass


class PrivateNetworkRejected(TargetURLRejected):
    """The resolved destination is private, reserved, multicast, or otherwise non-public."""


class RedirectedToPrivateNetwork(TargetURLRejected):
    """A redirect attempted to pivot the request into a private network."""


class UnsupportedMediaType(Exception):
    pass


class UnsupportedContentEncoding(Exception):
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


class UpstreamRenderError(Exception):
    pass


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(
        self,
        host: str,
        address: str,
        port: int,
        timeout: float,
    ) -> None:
        super().__init__(host, port=port, timeout=timeout)
        self._address = address

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._address, self.port),
            self.timeout,
            self.source_address,
        )
        if self._tunnel_host:
            self._tunnel()


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        host: str,
        address: str,
        port: int,
        timeout: float,
    ) -> None:
        super().__init__(
            host,
            port=port,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
        self._address = address

    def connect(self) -> None:
        raw_socket = socket.create_connection(
            (self._address, self.port),
            self.timeout,
            self.source_address,
        )
        if self._tunnel_host:
            self._tunnel()
        self.sock = self._context.wrap_socket(
            raw_socket,
            server_hostname=self._tunnel_host or self.host,
        )


def resolve_public_addresses(
    host: str,
    port: int,
) -> tuple[str, ...]:
    try:
        results = socket.getaddrinfo(
            host,
            port,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as error:
        raise TargetURLRejected("The target hostname could not be resolved") from error

    addresses = tuple(dict.fromkeys(result[4][0] for result in results))
    if not addresses:
        raise TargetURLRejected("The target hostname could not be resolved")

    for address in addresses:
        try:
            parsed_address = ipaddress.ip_address(address.split("%", 1)[0])
        except ValueError as error:
            raise TargetURLRejected("The target hostname resolved to an invalid address") from error

        # Reject non-public and multicast destinations, including IPv6
        # wrappers whose embedded IPv4 destination is non-public.
        if (
            not parsed_address.is_global
            or parsed_address.is_multicast
            or _is_nat64_or_6to4_address(str(parsed_address))
        ):
            raise PrivateNetworkRejected("The target hostname resolves to a non-public address")

    return addresses


def _is_ambiguous_numeric_host(host: str) -> bool:
    """True for non-canonical numeric host forms that should not reach DNS."""
    candidate = host.strip().rstrip(".").lower()
    if not candidate:
        return False

    try:
        ipaddress.ip_address(candidate)
        return False
    except ValueError:
        pass

    if re.fullmatch(r"0*[0-9]{1,10}", candidate):
        return True

    if re.fullmatch(r"0x[0-9a-f]+", candidate) or re.fullmatch(
        r"0x[0-9a-f]+(?:\.0x[0-9a-f]+){1,3}",
        candidate,
    ):
        return True

    if re.fullmatch(
        r"(?:0x[0-9a-f]+|0[0-7]*|[0-9]+)(?:\.(?:0x[0-9a-f]+|0[0-7]*|[0-9]+)){1,3}",
        candidate,
    ):
        return True

    if re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,2}", candidate):
        return True

    if re.fullmatch(
        r"(?:[0-9a-f:]*:)?(?:ffff:)?(?:0{1,4}:)?[0-9]+(?:\.[0-9]+){3}",
        candidate,
    ):
        return True

    return False


def _parse_target(
    url: str,
    settings: Settings | None = None,
) -> tuple[object, str, int, str]:
    if any(character in url for character in "\r\n\t"):
        raise TargetURLRejected("The URL contains invalid characters")

    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise TargetURLRejected("URL must be an absolute HTTP or HTTPSURL")
        if parsed.username is not None or parsed.password is not None:
            raise TargetURLRejected("URLs containing credentials are not allowed")

        host = parsed.hostname.encode("idna").decode("ascii")

        if _is_ambiguous_numeric_host(host):
            raise TargetURLRejected(
                "Ambiguous numeric host forms are not allowed; use a canonical domain name or canonical IP literal"
            )

        if parsed.port is None:
            port = 443 if parsed.scheme == "https" else 80
        else:
            port = parsed.port

        allowed_ports = (
            getattr(
                settings,
                "allowed_port_set",
                lambda: {80, 443},
            )()
            if settings is not None
            else {80, 443}
        )
        if port not in allowed_ports:
            raise TargetURLRejected("Only ports 80 and 443 are allowed by default")

        if _is_nat64_or_6to4_address(host):
            raise TargetURLRejected(
                "URL host uses an IPv4-mapped, NAT64, or 6to4 address embedding "
                "a non-public IPv4 destination, which is not allowed"
            )

    except (UnicodeError, ValueError) as error:
        if isinstance(error, TargetURLRejected):
            raise
        raise TargetURLRejected("The target URL is malformed") from error

    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"

    path = quote(
        path,
        safe="/?&=%:@+;,-._~!*'()$",
    )
    return parsed, host, port, path


def _make_connection(
    parsed,
    host: str,
    address: str,
    port: int,
    timeout: float,
):
    connection_type = _PinnedHTTPSConnection if parsed.scheme == "https" else _PinnedHTTPConnection
    return connection_type(
        host,
        address,
        port,
        timeout,
    )


def _host_header(
    host: str,
    port: int,
    scheme: str,
) -> str:
    formatted_host = f"[{host}]" if ":" in host else host
    default_port = 443 if scheme == "https" else 80
    return formatted_host if port == default_port else f"{formatted_host}:{port}"


def fetch_html(url: str, settings: Settings) -> bytes:
    """Fetch HTML bytes, following redirects and re-validating every hop."""
    return fetch_html_document(url, settings).body


def _is_multicast_address(host: str) -> bool:
    """True when host is a literal multicast address."""
    try:
        return ipaddress.ip_address(host).is_multicast
    except ValueError:
        return False


def _embedded_ipv4(
    address: ipaddress.IPv6Address,
) -> ipaddress.IPv4Address | None:
    """IPv4 address embedded in IPv4-mapped, NAT64, or 6to4 IPv6."""
    mapped = address.ipv4_mapped
    if mapped is not None:
        return mapped

    packed = address.packed

    if packed[:12] == bytes.fromhex("0000000000000000ffff0000"):
        return ipaddress.IPv4Address(packed[12:16])

    if packed[:12] == bytes.fromhex("0064ff9b0000000000000000"):
        return ipaddress.IPv4Address(packed[12:16])

    if packed[:2] == b"\x20\x02":
        return ipaddress.IPv4Address(packed[2:6])

    return None


def _is_nat64_or_6to4_address(host: str) -> bool:
    """True when an IPv6 literal embeds a non-public IPv4 address."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False

    if address.version != 6:
        return False

    embedded = _embedded_ipv4(address)
    if embedded is None:
        return False

    return not embedded.is_global or embedded.is_multicast


def fetch_html_document(
    url: str,
    settings: Settings,
) -> FetchedHTML:
    """Fetch a public HTML page, following redirects and re-validating every hop."""
    current_url = url
    current_scheme = urlsplit(url).scheme
    is_redirect_hop = False

    for _ in range(settings.max_redirects + 1):
        parsed, host, port, path = _parse_target(
            current_url,
            settings,
        )

        if port not in settings.allowed_port_set():
            raise TargetURLRejected(
                f"Port {port} is not in the allowed port list "
                f"(default: 80/443, extra: "
                f"{settings.allowed_ports or 'none'})"
            )

        if _is_multicast_address(host):
            raise TargetURLRejected(f"Multicast address {host} is not allowed (IPv4: 224.0.0.0/4, IPv6: ff00::/8)")

        if _is_nat64_or_6to4_address(host):
            raise TargetURLRejected(
                "URL host uses an IPv4-mapped, NAT64, or 6to4 address embedding "
                "a non-public IPv4 destination, which is not allowed"
            )

        if parsed.scheme != current_scheme:
            if current_scheme == "https" and parsed.scheme == "http":
                raise TargetURLRejected("Redirects from HTTPS to HTTP are not allowed")
            current_scheme = parsed.scheme

        try:
            addresses = resolve_public_addresses(
                host,
                port,
            )
        except PrivateNetworkRejected as error:
            if is_redirect_hop:
                raise RedirectedToPrivateNetwork("A redirect attempted to access a private network address") from error
            raise
        connection = None
        response = None
        last_error = None

        for address in addresses:
            candidate = _make_connection(
                parsed,
                host,
                address,
                port,
                settings.request_timeout_seconds,
            )

            try:
                candidate.request(
                    "GET",
                    path,
                    headers={
                        "Accept": ("text/html, application/xhtml+xml"),
                        "Accept-Encoding": "identity",
                        "Connection": "close",
                        "Host": _host_header(
                            host,
                            port,
                            parsed.scheme,
                        ),
                        "User-Agent": get_user_agent(settings),
                    },
                )
                response = candidate.getresponse()
                connection = candidate
                break
            except (OSError, http.client.HTTPException) as error:
                last_error = error
                candidate.close()
                continue

        if connection is None or response is None:
            raise last_error or OSError("No validated address could be connected to")

        try:
            status = response.status

            if status in REDIRECT_STATUSES:
                location = response.getheader("Location")
                if not location:
                    raise UpstreamHTTPError(
                        status,
                        "redirect without a Location header",
                    )
                current_url = urljoin(
                    current_url,
                    location,
                )
                is_redirect_hop = True
                continue

            if not 200 <= status < 300:
                raise UpstreamHTTPError(
                    status,
                    response.reason or "upstream error",
                )

            content_type = response.getheader(
                "Content-Type",
                "",
            )
            body = _read_html_response(
                response,
                settings.max_html_bytes,
            )

            return FetchedHTML(
                body=body,
                charset=_content_charset(content_type),
                final_url=current_url,
            )
        finally:
            connection.close()

    raise TooManyRedirects("The target exceeded the redirect limit")


async def fetch_rendered_html_document(
    url: str,
    settings: Settings,
) -> FetchedHTML:
    """Render a public page in Chromium and return its post-JavaScript HTML."""
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import Route, async_playwright
    from playwright.async_api import (
        TimeoutError as PlaywrightTimeoutError,
    )

    _, host, port, _ = _parse_target(url, settings)
    await asyncio.to_thread(
        resolve_public_addresses,
        host,
        port,
    )

    blocked_targets: list[Exception] = []
    browser = None

    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            context = await browser.new_context(
                service_workers="block",
            )
            page = await context.new_page()

            async def validate_request(
                route: Route,
            ) -> None:
                request = route.request
                if request.resource_type in {
                    "image",
                    "media",
                    "font",
                }:
                    await route.abort()
                    return

                request_url = urlsplit(request.url)
                if request_url.scheme in {
                    "data",
                    "blob",
                    "about",
                }:
                    await route.continue_()
                    return

                if request_url.scheme not in {
                    "http",
                    "https",
                }:
                    blocked_targets.append(TargetURLRejected("The page attempted to access a non-HTTP resource"))
                    await route.abort()
                    return

                redirect_count = 0
                redirected_request = request.redirected_from
                while redirected_request is not None:
                    redirect_count += 1
                    redirected_request = redirected_request.redirected_from

                if redirect_count > settings.max_redirects:
                    blocked_targets.append(TooManyRedirects("The target exceeded the redirect limit"))
                    await route.abort()
                    return

                try:
                    (
                        _,
                        request_host,
                        request_port,
                        _,
                    ) = _parse_target(
                        request.url,
                        settings,
                    )
                    await asyncio.to_thread(
                        resolve_public_addresses,
                        request_host,
                        request_port,
                    )
                except TargetURLRejected as error:
                    blocked_targets.append(error)
                    await route.abort()
                    return

                await route.continue_()

            await page.route(
                "**/*",
                validate_request,
            )

            try:
                response = await page.goto(
                    url,
                    wait_until="networkidle",
                    timeout=int(settings.request_timeout_seconds * 1000),
                )
            except PlaywrightTimeoutError as error:
                if blocked_targets:
                    raise blocked_targets[0] from error
                raise TimeoutError("The target did not finish rendering intime") from error
            except PlaywrightError as error:
                if blocked_targets:
                    raise blocked_targets[0] from error
                raise UpstreamRenderError("The target could not be rendered") from error

            if blocked_targets:
                raise blocked_targets[0]
            if response is None:
                raise UpstreamRenderError("The browser did not receive a page response")
            if not 200 <= response.status < 300:
                raise UpstreamHTTPError(
                    response.status,
                    response.reason or "upstream error",
                )

            content_type = response.headers.get(
                "content-type",
                "",
            )
            media_type = content_type.split(";", 1)[0].strip().lower()
            if media_type not in {
                "text/html",
                "application/xhtml+xml",
            }:
                raise UnsupportedMediaType("Only HTML/XHTML responses are supported")

            html = await page.content()
            body = html.encode("utf-8")

            if len(body) > settings.max_html_bytes:
                raise PayloadTooLarge("Rendered HTML may not exceed 1 MiB")

            return FetchedHTML(
                body=body,
                charset="utf-8",
                final_url=page.url,
            )
        finally:
            if browser is not None:
                await browser.close()


def _content_charset(content_type: str) -> str | None:
    headers = Message()
    headers["content-type"] = content_type
    charset = headers.get_content_charset()

    if charset is None:
        return None

    try:
        codecs.lookup(charset)
    except LookupError:
        logger.warning(
            "upstream_invalid_charset charset=%s",
            charset,
        )
        return None

    return charset


def _read_html_response(
    response,
    max_bytes: int,
) -> bytes:
    content_type = response.getheader(
        "Content-Type",
        "",
    )
    media_type = content_type.split(";", 1)[0].strip().lower()

    if media_type not in {
        "text/html",
        "application/xhtml+xml",
    }:
        raise UnsupportedMediaType("Only HTML/XHTML responses are supported")

    content_encoding = (
        response.getheader(
            "Content-Encoding",
            "identity",
        )
        .strip()
        .lower()
    )

    if content_encoding not in {
        "",
        "identity",
        "gzip",
        "x-gzip",
    }:
        raise UnsupportedContentEncoding(f"Unsupported content encoding: {content_encoding}")

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
            break

        if len(html_bytes) + len(chunk) > max_bytes:
            raise PayloadTooLarge("HTML responses may not exceed 1 MiB")

        html_bytes.extend(chunk)

    if content_encoding in {"gzip", "x-gzip"}:
        decompressor = zlib.decompressobj(
            16 + zlib.MAX_WBITS,
        )

        try:
            decoded = decompressor.decompress(
                bytes(html_bytes),
                max_bytes + 1,
            )
        except zlib.error as error:
            raise UnsupportedContentEncoding("The gzip-compressed responseis invalid") from error

        if len(decoded) > max_bytes or decompressor.unconsumed_tail:
            raise PayloadTooLarge("Decompressed HTML responses may not exceed 1 MiB")

        try:
            decoded += decompressor.flush(max_bytes - len(decoded) + 1)
        except zlib.error as error:
            raise UnsupportedContentEncoding("The gzip-compressed responseis invalid") from error

        if not decompressor.eof or decompressor.unused_data:
            raise UnsupportedContentEncoding("The gzip-compressed responseis incomplete or malformed")

        return decoded

    return bytes(html_bytes)
