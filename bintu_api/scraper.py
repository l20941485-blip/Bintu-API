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
from urllib.parse import quote, urljoin, urlsplit, urlunsplit


from bs4 import BeautifulSoup
from bs4.element import NavigableString


from bintu_api.page_noise import should_drop_title, strip_permalinks
from bintu_api.settings import Settings



logger = logging.getLogger(__name__)
READ_CHUNK_BYTES = 4096
REDIRECT_STATUSES = {301, 302, 303, 307, 308}



def get_user_agent(settings) -> str:
    """Build the honest, identifiable User-Agent: BintuBot/<version> (+<info url>; <contact>).


    The parenthesised parts appear only for settings that are actually configured.
    Never imitates a browser.
    """
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



BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "br",
    "dd",
    "div",
    "dl",
    "dt",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "tbody",
    "tfoot",
    "thead",
    "ul",
}



@dataclass(frozen=True)
class FetchedHTML:
    body: bytes
    charset: str | None
    final_url: str | None = None



@dataclass(frozen=True)
class ExtractedText:
    text: str
    truncated: bool



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
        _compute_approx_tokens(html_text)
        - _compute_approx_tokens(extracted_text),
    )



class TargetURLRejected(ValueError):
    pass



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
        super().__init__(
            f"Upstream returned HTTP {status_code} {reason}".strip()
        )



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
        raise TargetURLRejected(
            "The target hostname could not be resolved"
        ) from error


    addresses = tuple(
        dict.fromkeys(result[4][0] for result in results)
    )
    if not addresses:
        raise TargetURLRejected(
            "The target hostname could not be resolved"
        )


    for address in addresses:
        try:
            parsed_address = ipaddress.ip_address(
                address.split("%", 1)[0]
            )
        except ValueError as error:
            raise TargetURLRejected(
                "The target hostname resolved to an invalid address"
            ) from error


        # Reject non-public and multicast destinations, including IPv6
        # wrappers whose embedded IPv4 destination is non-public.
        if (
            not parsed_address.is_global
            or parsed_address.is_multicast
            or _is_nat64_or_6to4_address(str(parsed_address))
        ):
            raise TargetURLRejected(
                "The target hostname resolves to a non-public address"
            )


    return addresses



def _is_ambiguous_numeric_host(host: str) -> bool:
    """True for non-canonical numeric host forms that should not reach DNS.


    These forms can encode private, loopback, metadata, or otherwise unsafe
    IPv4 addresses while looking like ordinary hostnames. Reject them before
    DNS resolution so hostile URLs fail immediately rather than after a
    resolver timeout.
    """
    candidate = host.strip().rstrip(".").lower()
    if not candidate:
        return False


    # Canonical IPv4 and IPv6 literals are handled by the dedicated IP checks;
    # do not classify those as ambiguous here.
    try:
        ipaddress.ip_address(candidate)
        return False
    except ValueError:
        pass


    # Decimal IPv4: 2130706433, 02130706433, etc.
    if re.fullmatch(r"0*[0-9]{1,10}", candidate):
        return True


    # Hexadecimal IPv4: 0x7f000001, 0x7f.0.0.1.
    if re.fullmatch(r"0x[0-9a-f]+", candidate) or re.fullmatch(
        r"0x[0-9a-f]+(?:\.0x[0-9a-f]+){1,3}",
        candidate,
    ):
        return True


    # Dotted forms with any hex/octal component: 0x7f.0.0.1, 0177.0.0.1.
    if re.fullmatch(
        r"(?:0x[0-9a-f]+|0[0-7]*|[0-9]+)(?:\.(?:0x[0-9a-f]+|0[0-7]*|[0-9]+)){1,3}",
        candidate,
    ):
        return True


    # Short-form IPv4: 127.1, 127.0.1, etc.
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,2}", candidate):
        return True


    # IPv4-mapped IPv6 written with an IPv4 tail: ::ffff:127.0.0.1.
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
        raise TargetURLRejected(
            "The URL contains invalid characters"
        )


    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
        ):
            raise TargetURLRejected(
                "URL must be an absolute HTTP or HTTPS URL"
            )
        if (
            parsed.username is not None
            or parsed.password is not None
        ):
            raise TargetURLRejected(
                "URLs containing credentials are not allowed"
            )


        host = parsed.hostname.encode("idna").decode("ascii")


        # Reject ambiguous numeric host forms before DNS.
        if _is_ambiguous_numeric_host(host):
            raise TargetURLRejected(
                "Ambiguous numeric host forms are not allowed; use a canonical "
                "domain name or canonical IP literal"
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
            raise TargetURLRejected(
                "Only ports 80 and 443 are allowed by default"
            )


        # Reject NAT64 or 6to4 embedding private/metadata IPv4.
        if _is_nat64_or_6to4_address(host):
            raise TargetURLRejected(
                "URL host uses an IPv4-mapped, NAT64, or 6to4 address embedding "
                    "a non-public IPv4 destination, which is not allowed"
            )


    except (UnicodeError, ValueError) as error:
        if isinstance(error, TargetURLRejected):
            raise
        raise TargetURLRejected(
            "The target URL is malformed"
        ) from error


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
    connection_type = (
        _PinnedHTTPSConnection
        if parsed.scheme == "https"
        else _PinnedHTTPConnection
    )
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
    return (
        formatted_host
        if port == default_port
        else f"{formatted_host}:{port}"
    )



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


    # IPv4-translated addresses (::ffff:0:0:0/96) also embed an IPv4
    # destination in their final 32 bits.
    if packed[:12] == bytes.fromhex(
        "0000000000000000ffff0000"
    ):
        return ipaddress.IPv4Address(packed[12:16])


    if packed[:12] == bytes.fromhex(
        "0064ff9b0000000000000000"
    ):
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


    return (
        not embedded.is_global or embedded.is_multicast
    )



def fetch_html_document(
    url: str,
    settings: Settings,
) -> FetchedHTML:
    """Fetch a public HTML page, following redirects and re-validating every hop."""
    current_url = url
    current_scheme = urlsplit(url).scheme


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
            raise TargetURLRejected(
                f"Multicast address {host} is not allowed "
                "(IPv4: 224.0.0.0/4, IPv6: ff00::/8)"
            )


        if _is_nat64_or_6to4_address(host):
            raise TargetURLRejected(
                "URL host uses an IPv4-mapped, NAT64, or 6to4 address embedding "
                    "a non-public IPv4 destination, which is not allowed"
            )


        if parsed.scheme != current_scheme:
            if (
                current_scheme == "https"
                and parsed.scheme == "http"
            ):
                raise TargetURLRejected(
                    "Redirects from HTTPS to HTTP are not allowed"
                )
            current_scheme = parsed.scheme


        addresses = resolve_public_addresses(
            host,
            port,
        )
        connection = None
        response = None
        last_error = None


        # Try each validated public address. A connection failure at one
        # address should not fail the request when another address works.
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
                        "Accept": (
                            "text/html, application/xhtml+xml"
                        ),
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
            raise last_error or OSError(
                "No validated address could be connected to"
            )


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


    raise TooManyRedirects(
        "The target exceeded the redirect limit"
    )



async def fetch_rendered_html_document(
    url: str,
    settings: Settings,
) -> FetchedHTML:
    """Render a public page in Chromium and return its post-JavaScript HTML."""
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import (
        TimeoutError as PlaywrightTimeoutError,
    )
    from playwright.async_api import Route, async_playwright


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
                    blocked_targets.append(
                        TargetURLRejected(
                            "The page attempted to access "
                            "a non-HTTP resource"
                        )
                    )
                    await route.abort()
                    return


                redirect_count = 0
                redirected_request = (
                    request.redirected_from
                )
                while redirected_request is not None:
                    redirect_count += 1
                    redirected_request = (
                        redirected_request.redirected_from
                    )


                if redirect_count > settings.max_redirects:
                    blocked_targets.append(
                        TooManyRedirects(
                            "The target exceeded the "
                            "redirect limit"
                        )
                    )
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
                    timeout=int(
                        settings.request_timeout_seconds
                        * 1000
                    ),
                )
            except PlaywrightTimeoutError as error:
                if blocked_targets:
                    raise blocked_targets[0] from error
                raise TimeoutError(
                    "The target did not finish rendering in time"
                ) from error
            except PlaywrightError as error:
                if blocked_targets:
                    raise blocked_targets[0] from error
                raise UpstreamRenderError(
                    "The target could not be rendered"
                ) from error


            if blocked_targets:
                raise blocked_targets[0]
            if response is None:
                raise UpstreamRenderError(
                    "The browser did not receive a page response"
                )
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
                raise UnsupportedMediaType(
                    "Only HTML/XHTML responses are supported"
                )


            html = await page.content()
            body = html.encode("utf-8")


            if len(body) > settings.max_html_bytes:
                raise PayloadTooLarge(
                    "Rendered HTML may not exceed 1 MiB"
                )


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
        raise UnsupportedMediaType(
            "Only HTML/XHTML responses are supported"
        )


    content_encoding = response.getheader(
        "Content-Encoding",
        "identity",
    ).strip().lower()


    if content_encoding not in {
        "",
        "identity",
        "gzip",
        "x-gzip",
    }:
        raise UnsupportedContentEncoding(
            f"Unsupported content encoding: {content_encoding}"
        )


    content_length = response.getheader("Content-Length")
    if content_length is not None:
        try:
            if int(content_length) > max_bytes:
                raise PayloadTooLarge(
                    "HTML responses may not exceed 1 MiB"
                )
        except ValueError:
            pass


    html_bytes = bytearray()


    while True:
        remaining = max_bytes - len(html_bytes)
        chunk = response.read(
            min(READ_CHUNK_BYTES, remaining + 1)
        )


        if not chunk:
            break


        if len(html_bytes) + len(chunk) > max_bytes:
            raise PayloadTooLarge(
                "HTML responses may not exceed 1 MiB"
            )


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
            raise UnsupportedContentEncoding(
                "The gzip-compressed response is invalid"
            ) from error


        if (
            len(decoded) > max_bytes
            or decompressor.unconsumed_tail
        ):
            raise PayloadTooLarge(
                "Decompressed HTML responses may not exceed 1 MiB"
            )


        try:
            decoded += decompressor.flush(
                max_bytes - len(decoded) + 1
            )
        except zlib.error as error:
            raise UnsupportedContentEncoding(
                "The gzip-compressed response is invalid"
            ) from error


        if (
            not decompressor.eof
            or decompressor.unused_data
        ):
            raise UnsupportedContentEncoding(
                "The gzip-compressed response is "
                "incomplete or malformed"
            )


        return decoded


    return bytes(html_bytes)



def extract_text(
    html_bytes: bytes,
    max_characters: int,
    include_nav: bool = False,
    include_header: bool = False,
    include_footer: bool = False,
    from_encoding: str | None = None,
) -> str:
    return extract_text_result(
        html_bytes,
        max_characters,
        include_nav=include_nav,
        include_header=include_header,
        include_footer=include_footer,
        from_encoding=from_encoding,
    ).text



def _select_comment_thread_root(soup):
    """Select discussion content for comment-thread pages.


    Forums often place navigation, login controls, and site furniture outside
    semantic <main>/<article> containers. When recognizable comment bodies
    exist, build a focused root from the submission title and comments.
    """
    comment_nodes = soup.select(
        "div.commtext, span.commtext, td.comment, "
        "[class*='comment-body'], [data-testid*='comment']"
    )


    if not comment_nodes:
        return None


    thread_root = soup.new_tag("div")
    thread_root["class"] = "bintu-comment-thread"


    title_anchor = soup.select_one(
        "a.titlelink, .titleline a, .storylink"
    )
    if title_anchor:
        heading = soup.new_tag("h1")
        heading.string = title_anchor.get_text(" ", strip=True)
        thread_root.append(heading)


    for comment in comment_nodes:
        wrapper = soup.new_tag("p")
        wrapper.append(comment.extract())
        thread_root.append(wrapper)


    container = soup.body or soup
    container.append(thread_root)
    return thread_root



def _pick_content_root(soup, *, min_ratio: float = 0.3):
    """Select a root containing a meaningful share of visible page text.

    A homepage may contain an <article> for only its hero story. Prefer a
    semantic container only when it contains enough of the page text;
    otherwise retain the whole document.
    """
    body = soup.body or soup
    total = len(body.get_text(" ", strip=True))

    candidates = (
        soup.find("article"),
        soup.find("main"),
        soup.find(
            attrs={
                "role": re.compile(r"^main$", re.IGNORECASE),
            }
        ),
        soup.find(
            id=re.compile(
                r"^(?:main|content|article|post|entry)"
                r"(?:[-_](?:main|content|article|body))?$",
                re.IGNORECASE,
            )
        ),
        soup.find(
            class_=re.compile(
                r"^(?:main|content|article|post|entry)"
                r"(?:[-_](?:main|content|article|body))?$",
                re.IGNORECASE,
            )
        ),
    )

    for candidate in candidates:
        if candidate is None:
            continue

        candidate_text = len(candidate.get_text(" ", strip=True))
        if candidate_text >= total * min_ratio:
            return candidate

    return soup


PRE_NL = "\x01"
PRE_SP = "\x02"
PRE_TAB = "\x03"

_LANG_RE = re.compile(r"(?:language|lang|highlight(?:-source)?)-([A-Za-z0-9+#_-]+)")


def _fence_language(pre) -> str:
    """Best-effort language tag from <pre>, <code>, or wrapper classes."""
    candidates = [pre]
    code = pre.find("code")
    if code is not None:
        candidates.append(code)
    candidates.extend(list(pre.parents)[:3])
    for node in candidates:
        classes = node.get("class", []) if hasattr(node, "get") else []
        for name in classes if isinstance(classes, list) else [classes]:
            match = _LANG_RE.search(str(name))
            if match:
                language = match.group(1).lower()
                return "" if language in {"default", "none", "text", "plain"} else language
    return ""


def protect_pre_blocks(root, boundary: str) -> int:
    """Replace <pre> blocks with fenced placeholders that survive normalization."""
    replaced = 0
    for pre in root.find_all("pre"):
        code = pre.get_text().replace("\r\n", "\n").replace("\r", "\n").strip("\n")
        if not code.strip():
            pre.decompose()
            continue
        shielded = (
            code.replace("\u00a0", " ")
            .replace("\n", PRE_NL)
            .replace(" ", PRE_SP)
            .replace("\t", PRE_TAB)
        )
        fence = f"```{_fence_language(pre)}{PRE_NL}{shielded}{PRE_NL}```"
        pre.replace_with(NavigableString(f"{boundary}{fence}{boundary}"))
        replaced += 1
    return replaced


def restore_pre_placeholders(text: str) -> str:
    """Restore whitespace shielded by protect_pre_blocks."""
    return text.replace(PRE_NL, "\n").replace(PRE_SP, " ").replace(PRE_TAB, "\t")


def close_open_fence(text: str) -> str:
    """Close a Markdown code fence left open by truncation."""
    open_fences = sum(1 for line in text.split("\n") if line.startswith("```")) % 2
    return f"{text}\n```" if open_fences else text


def _truncate_extracted_text(
    text: str,
    max_characters: int,
) -> ExtractedText:
    if len(text) <= max_characters:
        return ExtractedText(
            text=text,
            truncated=False,
        )

    # Reserve room for a closing code fence if truncation cuts one open.
    limit = max_characters - 4 if "```" in text else max_characters
    truncated_text = text[:limit]

    last_boundary = max(
        truncated_text.rfind("\n"),
        truncated_text.rfind(" "),
    )

    if last_boundary > 0:
        truncated_text = truncated_text[:last_boundary].rstrip()

    truncated_text = close_open_fence(truncated_text)

    return ExtractedText(
        text=truncated_text,
        truncated=True,
    )


def _trafilatura_fallback(
    html_bytes: bytes,
    max_characters: int,
    from_encoding: str | None,
    base_url: str | None,
) -> str | None:
    """Extract main content with Trafilatura when BeautifulSoup is too sparse."""
    import trafilatura

    try:
        html = html_bytes.decode(
            from_encoding or "utf-8",
            errors="replace",
        )
        text = trafilatura.extract(
            html,
            url=base_url,
            output_format="txt",
            include_links=True,
            include_tables=True,
        )
    except Exception as error:
        logger.warning(
            "trafilatura_fallback_failed error=%s",
            error,
        )
        return None

    if not text:
        return None

    lines = []
    for line in text.splitlines():
        line = re.sub(r"[\u200b\u2060\ufeff]", " ", line)
        line = re.sub(r"\s+", " ", line).strip()
        line = re.sub(r"\s+([,.;:!?])", r"\1", line)
        if line:
            lines.append(line)

    return "\n".join(lines)


def extract_text_result(
    html_bytes: bytes,
    max_characters: int,
    include_nav: bool = False,
    include_header: bool = False,
    include_footer: bool = False,
    from_encoding: str | None = None,
    base_url: str | None = None,
) -> ExtractedText:
    """Extract visible text from HTML bytes."""
    soup = BeautifulSoup(
        html_bytes,
        "html.parser",
        from_encoding=from_encoding,
    )


    tags_to_remove = [
        "button",
        "iframe",
        "input",
        "noscript",
        "script",
        "select",
        "style",
        "svg",
        "template",
        "textarea",
    ]


    if not include_nav:
        tags_to_remove.append("nav")
    if not include_header:
        tags_to_remove.append("header")
    if not include_footer:
        tags_to_remove.append("footer")


    for node in soup(tags_to_remove):
        node.decompose()

    strip_permalinks(soup)


    for node in soup.find_all(True):
        attributes = node.attrs or {}


        if (
            "hidden" in attributes
            or str(
                attributes.get("aria-hidden") or ""
            ).lower()
            == "true"
        ):
            node.decompose()
            continue


        style = re.sub(
            r"\s+",
            "",
            str(attributes.get("style") or "").lower(),
        )
        if (
            "display:none" in style
            or "visibility:hidden" in style
        ):
            node.decompose()
            continue


        role = str(
            attributes.get("role") or ""
        ).lower()
        if role in {
            "dialog",
            "menu",
            "menuitem",
            "toolbar",
        }:
            node.decompose()
            continue


        classes = attributes.get("class", [])
        class_names = (
            classes
            if isinstance(classes, list)
            else [classes]
        )
        identifiers = " ".join(
            [
                str(attributes.get("id") or ""),
                *(str(value) for value in class_names),
            ]
        )
        normalized_identifiers = re.sub(
            r"([a-z])([A-Z])",
            r"\1 \2",
            identifiers,
        ).lower()


        if re.search(
            r"\b(?:share|social|related|recommend(?:ation)?|"
            r"advert(?:isement)?|"
            r"cookie|consent|newsletter|subscribe|breadcrumb|"
            r"promo(?:tion)?|paywall)\b",
            normalized_identifiers,
        ):
            node.decompose()


    page_title = (
        soup.title.get_text(" ", strip=True)
        if soup.title
        else ""
    )
    if soup.title:
        soup.title.decompose()

    comment_thread_root = _select_comment_thread_root(soup)

    content_root = (
        comment_thread_root
        or _pick_content_root(soup)
    )

    content_roots = [content_root]


    if content_root is not soup:
        for tag_name, should_include in (
            ("nav", include_nav),
            ("header", include_header),
            ("footer", include_footer),
        ):
            if should_include:
                content_roots.extend(
                    node
                    for node in soup.find_all(tag_name)
                    if all(
                        parent is not content_root
                        for parent in node.parents
                    )
                )


    first_heading = content_root.find(
        ["h1", "h2", "h3", "h4", "h5", "h6"]
    )
    heading_text = (
        first_heading.get_text(" ", strip=True)
        if first_heading
        else ""
    )


    normalized_title = re.sub(
        r"\s+",
        " ",
        page_title,
    ).strip()
    normalized_heading = re.sub(
        r"\s+",
        " ",
        heading_text,
    ).strip()


    if (
        normalized_title
        and should_drop_title(normalized_title, normalized_heading)
    ):
        normalized_title = ""


    for anchor in soup.find_all("a", href=True):
        if anchor.find_parent("pre"):
            continue

        label = re.sub(
            r"\s+",
            " ",
            anchor.get_text(),
        ).strip()
        href = anchor["href"].strip()


        if not label or not href or not base_url:
            continue


        resolved = urlsplit(
            urljoin(base_url, href)
        )


        if (
            resolved.scheme
            not in {"http", "https"}
            or not resolved.hostname
        ):
            continue


        if (
            resolved.username is not None
            or resolved.password is not None
        ):
            continue


        destination = urlunsplit(
            (
                resolved.scheme,
                resolved.netloc,
                resolved.path,
                resolved.query,
                "",
            )
        )


        if destination != label:
            if anchor.find(list(BLOCK_TAGS)):
                anchor.append(
                    NavigableString(f" ({destination})")
                )
                anchor.unwrap()
            else:
                anchor.replace_with(
                    NavigableString(
                        f"{label} ({destination})"
                    )
                )


    boundary = "\x00BINTU_BLOCK_BOUNDARY\x00"


    while boundary in " ".join(
        root.get_text() for root in content_roots
    ):
        boundary += "\x00"


    for root in content_roots:
        protect_pre_blocks(root, boundary)

        for row in root.find_all("tr"):
            cells = row.find_all(
                ["th", "td"],
                recursive=False,
            )


            if cells:
                cell_text = [
                    re.sub(
                        r"\s+",
                        " ",
                        cell.get_text(),
                    ).strip()
                    for cell in cells
                ]
                row_text = " | ".join(cell_text)


                if row.find("th", recursive=False):
                    row_text = (
                        f"{row_text}{boundary}"
                        f"{' | '.join('---' for _ in cells)}"
                    )


                row.replace_with(
                    NavigableString(
                        f"{boundary}{row_text}{boundary}"
                    )
                )


        for node in root.find_all(
            ["h1", "h2", "h3", "h4", "h5", "h6"]
        ):
            level = int(node.name[1])
            heading = re.sub(
                r"\s+",
                " ",
                node.get_text(" ", strip=True),
            ).strip()
            node.replace_with(
                NavigableString(
                    f"{boundary}{'#' * level} "
                    f"{heading}{boundary}"
                )
            )


        for node in root.find_all(BLOCK_TAGS):
            node.insert_before(boundary)
            node.insert_after(boundary)


    text = boundary.join(
        root.get_text() for root in content_roots
    )


    lines = []


    for line in text.split(boundary):
        line = re.sub(
            r"[\u200b\u2060\ufeff]",
            " ",
            line,
        )
        line = re.sub(r"\s+", " ", line).strip()
        line = re.sub(r"\s+([,.;:!?])", r"\1", line)


        if line:
            lines.append(line)


    if normalized_title:
        lines.insert(0, f"# {normalized_title}")


    text = "\n".join(lines)
    text = restore_pre_placeholders(text)

    bs4_text = text.strip()
    minimum_useful_text = min(120, max_characters)

    fallback_text = None
    if len(bs4_text) == 0 and comment_thread_root is None:
        fallback_text = _trafilatura_fallback(
            html_bytes,
            max_characters,
            from_encoding,
            base_url,
        )

    if (
        fallback_text
        and len(fallback_text.strip())
        >= len(bs4_text) + 80
    ):
        if normalized_title:
            fallback_text = (
                f"# {normalized_title}\n{fallback_text}"
            )

        return _truncate_extracted_text(
            fallback_text,
            max_characters,
        )

    return _truncate_extracted_text(
        text,
        max_characters,
    )
