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

from bintu_api.settings import Settings


logger = logging.getLogger(__name__)
READ_CHUNK_BYTES = 4096
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
USER_AGENT = "BintuBot/1.1.0 (+https://bintu-api.example.com/bot-info; ops@example.com)"


def get_user_agent(settings) -> str:
    """Generate configurable compliance User-Agent string per C2 requirement.

    Format: BintuBot/<version> (+[BOT_INFO_URL]; [CONTACT_EMAIL])
    Never forges consumer browser signatures.
    """
    info_url = settings.bot_info_url or "https://bintu-api.example.com/bot-info"
    contact = settings.contact_email or "ops@example.com"
    return f"BintuBot/{settings.service_version} (+{info_url}; {contact})"
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
    """Compute approximate token count using ceil(characters / 4).

    Uses a dependency-free whitespace-split tokenizer.
    This represents a character bound, not a physical hardware tokenizer configuration.
    """
    return math.ceil(len(text) / 4)


def _compute_tokens_saved_estimate(raw_html_bytes: bytes, extracted_text: str) -> int:
    """Compute estimated structural payload reduction.

    approx_tokens(fetched HTML content) - approx_tokens(extracted Markdown output text),
    floored at 0.
    """
    raw_chars = len(raw_html_bytes.decode("utf-8", errors="replace"))
    approx_raw = _compute_approx_tokens(raw_html_bytes.decode("utf-8", errors="replace"))
    approx_extracted = _compute_approx_tokens(extracted_text)
    return max(0, approx_raw - approx_extracted)


# RFC 9309 Robots.txt Compliance - RobotsPolicy and parser
from collections import namedtuple

RobotsPolicy = namedtuple("RobotsPolicy", ["user_agent", "allow", "reason"])


def _parse_robots_txt(content: str, target_user_agent: str = "BintuBot") -> RobotsPolicy:
    """Parse a robots.txt file according to RFC 9309.

    Priority order:
    1. Specific User-agent match (e.g., User-agent: BintuBot)
    2. Global wildcard (*) fallback
    3. Default: if no rule matches, allow

    Returns a RobotsPolicy indicating whether scraping is allowed.
    """
    lines = content.splitlines()
    current_user_agent: str | None = None
    directives: dict[str, list[str]] = {"allow": [], "disallow": []}

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split(": ", 1)
        if len(parts) != 2:
            continue

        key, value = parts[0].strip().lower(), parts[1].strip()

        if key == "user-agent":
            user_agents = [u.strip() for u in value.split(",")]
            for ua in user_agents:
                if ua == target_user_agent or ua == "*":
                    current_user_agent = ua
                    break

        elif key in ("allow", "disallow") and current_user_agent is not None:
            if current_user_agent == target_user_agent or current_user_agent == "*":
                directives[key].append(value)

    # Check if we have a specific BintuBot match
    if current_user_agent == target_user_agent:
        allow = "disallow" not in directives or len(directives["disallow"]) == 0
        disallowed_paths = directives.get("disallow", [])
        return RobotsPolicy(
            user_agent=target_user_agent,
            allow=allow,
            reason=f"Matched User-agent: {target_user_agent}. Disallowed paths: {disallowed_paths}" if not allow else None,
        )

    # Fall back to global wildcard (*)
    current_user_agent = None
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(": ", 1)
        if len(parts) != 2:
            continue
        key, value = parts[0].strip().lower(), parts[1].strip()
        if key == "user-agent" and value.strip() == "*":
            current_user_agent = "*"
            break

    if current_user_agent == "*":
        allow = "disallow" not in directives or len(directives["disallow"]) == 0
        disallowed_paths = directives.get("disallow", [])
        return RobotsPolicy(
            user_agent="*",
            allow=allow,
            reason=f"Matched global wildcard (*). Disallowed paths: {disallowed_paths}" if not allow else None,
        )

    # Default: allow if no specific rule matches
    return RobotsPolicy(user_agent=target_user_agent, allow=True, reason=None)


def _check_robots_txt(
    host: str,
    settings: "Settings",
    http_client: callable,
) -> RobotsPolicy:
    """Check robots.txt for a given host using the SSRF-safe HTTP client.

    Cache origin policy structures locally for exactly 1 hour (configurable via
    robots_cache_ttl_seconds).

    HTTP Status Code Mapping:
    - 4xx: Map as explicit authorization to parse (allow)
    - 5xx or connection timeout: Map as total access restriction block (disallow)

    Returns RobotsPolicy with the decision.
    """
    from bintu_api.cache import TTLCache

    # Initialize per-robot cache if not exists
    if not hasattr(_check_robots_txt, "cache"):
        _check_robots_txt.cache = TTLCache(
            ttl=getattr(settings, "robots_cache_ttl_seconds", 3600),
            metadata=False,
        )

    cache_key = f"robots:{host.lower()}"
    cached = _check_robots_txt.cache.get(cache_key)
    if cached is not None:
        return cached

    # Build robots.txt URL
    scheme = "https" if host.startswith("https://") else "http"
    robots_url = f"{scheme}://{host}/robots.txt"

    # Use the SSRF-safe HTTP client
    try:
        status_code, body = http_client(robots_url, 443 if scheme == "https" else 80)
    except TimeoutError:
        policy = RobotsPolicy(user_agent="BintuBot", allow=False, reason="Connection timeout checking robots.txt")
        _check_robots_txt.cache[cache_key] = policy
        return policy
    except Exception as e:
        policy = RobotsPolicy(user_agent="BintuBot", allow=False, reason=f"Failed to fetch robots.txt: {e}")
        _check_robots_txt.cache[cache_key] = policy
        return policy

    # HTTP Status Code Mapping
    if status_code >= 500:
        policy = RobotsPolicy(user_agent="BintuBot", allow=False, reason=f"HTTP {status_code} error checking robots.txt")
        _check_robots_txt.cache[cache_key] = policy
        return policy

    if status_code in (401, 403, 429):
        # 4xx errors = explicit authorization to parse (allow)
        policy = RobotsPolicy(user_agent="BintuBot", allow=True, reason=f"HTTP {status_code} from robots.txt (authorized)")
        _check_robots_txt.cache[cache_key] = policy
        return policy

    if status_code == 402:
        policy = RobotsPolicy(user_agent="BintuBot", allow=False, reason="HTTP 402 Payment Required - access restricted")
        _check_robots_txt.cache[cache_key] = policy
        return policy

    if status_code == 200:
        policy = _parse_robots_txt(body.decode("utf-8", errors="replace"), target_user_agent="BintuBot")
        _check_robots_txt.cache[cache_key] = policy
        return policy

    # Other status codes - default to disallow
    policy = RobotsPolicy(user_agent="BintuBot", allow=False, reason=f"HTTP {status_code} from robots.txt")
    _check_robots_txt.cache[cache_key] = policy
    return policy


def check_robots_compliance(
    url: str,
    settings: "Settings",
    http_client: callable,
) -> tuple[bool, RobotsPolicy, dict]:
    """Check robots.txt compliance for a URL.

    Returns:
        (is_allowed: bool, policy: RobotsPolicy, provenance: dict)

    ROBOTS_MODE Behavior:
    - "enforce" (default): Immediately drop restricted actions with blocked_by_robots exception
    - "warn": Compile target data normally but append policy evaluation metrics into provenance.robots
    - "off": Skip robots.txt check entirely, is_allowed=True
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.hostname or ""

    if not host or settings.robots_mode == "off":
        return True, RobotsPolicy(user_agent="BintuBot", allow=True, reason="ROBOTS_MODE=off"), {}

    # Check robots.txt
    policy = _check_robots_txt(host, settings, http_client)

    if settings.robots_mode == "enforce":
        if not policy.allow:
            from fastapi import HTTPException

            raise HTTPException(
                status_code=403,
                detail={
                    "code": "blocked_by_robots",
                    "message": f"Scraping disallowed by robots.txt: {policy.reason or ''}",
                },
            )
        return True, policy, {}

    if settings.robots_mode == "warn":
        provenance = {"robots": {"allowed": policy.allow, "reason": policy.reason or ""}}
        return True, policy, provenance

    # Default fallback
    return True, policy, {}


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
        super().__init__(f"Upstream returned HTTP {status_code} {reason}".strip())


class TooManyRedirects(Exception):
    pass


class UpstreamRenderError(Exception):
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
            parsed_address = ipaddress.ip_address(address.split("%", 1)[0])
        except ValueError as error:
            raise TargetURLRejected("The target hostname resolved to an invalid address") from error
        # `is_global` alone is not enough: 224.0.0.0/4 and ff00::/8 are
        # "global" per the stdlib but are multicast, never web destinations.
        if not parsed_address.is_global or parsed_address.is_multicast:
            raise TargetURLRejected("The target hostname resolves to a non-public address")
    return addresses


def _parse_target(url: str, settings: Settings | None = None) -> tuple[object, str, int, str]:
    if any(character in url for character in "\r\n\t"):
        raise TargetURLRejected("The URL contains invalid characters")
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise TargetURLRejected("URL must be an absolute HTTP or HTTPS URL")
        if parsed.username is not None or parsed.password is not None:
            raise TargetURLRejected("URLs containing credentials are not allowed")
        host = parsed.hostname.encode("idna").decode("ascii")
        # `parsed.port` is 0 for an explicit ":0" and None when absent, so the
        # default port must only be applied when no port was given at all.
        # Silently turning ":0" into 80 would smuggle a malformed target past
        # the allow-list check below.
        if parsed.port is None:
            port = 443 if parsed.scheme == "https" else 80
        else:
            port = parsed.port
        # Only 80/443 (plus an operator-configured extra list) may be fetched:
        # arbitrary ports turn the service into a public host/port probe (S8).
        if port not in (settings.allowed_port_set() if settings is not None else {80, 443}):
            raise TargetURLRejected("Only ports 80 and 443 are allowed by default")
    except (UnicodeError, ValueError) as error:
        if isinstance(error, TargetURLRejected):
            raise
        raise TargetURLRejected("The target URL is malformed") from error

    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    # http.client encodes the request line as latin-1, so percent-encode anything
    # outside ASCII (already-encoded %XX sequences are preserved as-is).
    path = quote(path, safe="/?&=%:@+;,-._~!*'()$")
    return parsed, host, port, path


def _make_connection(parsed, host: str, address: str, port: int, timeout: float):
    connection_type = _PinnedHTTPSConnection if parsed.scheme == "https" else _PinnedHTTPConnection
    return connection_type(host, address, port, timeout)


def _host_header(host: str, port: int, scheme: str) -> str:
    formatted_host = f"[{host}]" if ":" in host else host
    default_port = 443 if scheme == "https" else 80
    return formatted_host if port == default_port else f"{formatted_host}:{port}"


def fetch_html(url: str, settings: Settings) -> bytes:
    """Fetch HTML bytes, following redirects and re-validating every hop."""
    return fetch_html_document(url, settings).body


def _is_multicast_address(host: str) -> bool:
    """Check if host is a multicast address.

    Blocks IPv4 multicast: 224.0.0.0/4
    Blocks IPv6 multicast: ff00::/8
    """
    try:
        # IPv4 multicast check
        if host.startswith('224.') or host.startswith('225.') or host.startswith('239.'):
            return True
        # IPv6 multicast check
        if host.startswith('ff'):
            return True
    except (AttributeError, ValueError):
        pass
    return False


def fetch_html_document(url: str, settings: Settings) -> FetchedHTML:
    """Fetch a public HTML page, following redirects and re-validating every hop.

    Each hop performs a fresh DNS resolution and pins the connection to a
    validated public address, so a public hostname can never redirect the
    request into a private network (DNS rebinding included).
    """
    current_url = url
    current_scheme = urlsplit(url).scheme
    for _ in range(settings.max_redirects + 1):
        parsed, host, port, path = _parse_target(current_url, settings)

        # S8: Runtime port validation in fetch loop (not just parse time)
        if port not in settings.allowed_port_set():
            raise TargetURLRejected(
                f"Port {port} is not in the allowed port list "
                f"(default: 80/443, extra: {settings.allowed_ports or 'none'})"
            )

        # S7: Multicast address block at resolution
        if _is_multicast_address(host):
            raise TargetURLRejected(
                f"Multicast address {host} is not allowed (IPv4: 224.0.0.0/4, "
                f"IPv6: ff00::/8)"
            )

        if parsed.scheme != current_scheme:
            if current_scheme == "https" and parsed.scheme == "http":
                # An https page must not hand us down to cleartext mid-chain:
                # cookies/keys sent on the first hop would leak upstream (S10).
                raise TargetURLRejected("Redirects from HTTPS to HTTP are not allowed")
            current_scheme = parsed.scheme
        address = resolve_public_addresses(host, port)[0]
        connection = _make_connection(parsed, host, address, port, settings.request_timeout_seconds)
        try:
            connection.request(
                "GET",
                path,
                headers={
                    "Accept": "text/html, application/xhtml+xml",
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                    "Host": _host_header(host, port, parsed.scheme),
                    "User-Agent": USER_AGENT,
                },
            )
            response = connection.getresponse()
            status = response.status
            if status in REDIRECT_STATUSES:
                location = response.getheader("Location")
                if not location:
                    raise UpstreamHTTPError(status, "redirect without a Location header")
                current_url = urljoin(current_url, location)
                continue
            if not 200 <= status < 300:
                raise UpstreamHTTPError(status, response.reason or "upstream error")
            content_type = response.getheader("Content-Type", "")
            body = _read_html_response(response, settings.max_html_bytes)
            return FetchedHTML(
                body=body,
                charset=_content_charset(content_type),
                final_url=current_url,
            )
        finally:
            connection.close()

    raise TooManyRedirects("The target exceeded the redirect limit")


async def fetch_rendered_html_document(url: str, settings: Settings) -> FetchedHTML:
    """Render a public page in Chromium and return its post-JavaScript HTML."""
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
    from playwright.async_api import Route, async_playwright

    _, host, port, _ = _parse_target(url, settings)
    await asyncio.to_thread(resolve_public_addresses, host, port)
    blocked_targets: list[Exception] = []
    browser = None

    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
            )
            context = await browser.new_context(service_workers="block")
            page = await context.new_page()

            async def validate_request(route: Route) -> None:
                request = route.request
                if request.resource_type in {"image", "media", "font"}:
                    await route.abort()
                    return

                request_url = urlsplit(request.url)
                if request_url.scheme in {"data", "blob", "about"}:
                    await route.continue_()
                    return
                if request_url.scheme not in {"http", "https"}:
                    blocked_targets.append(
                        TargetURLRejected("The page attempted to access a non-HTTP resource")
                    )
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
                    _, request_host, request_port, _ = _parse_target(request.url, settings)
                    await asyncio.to_thread(resolve_public_addresses, request_host, request_port)
                except TargetURLRejected as error:
                    blocked_targets.append(error)
                    await route.abort()
                    return
                await route.continue_()

            await page.route("**/*", validate_request)
            try:
                response = await page.goto(
                    url,
                    wait_until="networkidle",
                    timeout=int(settings.request_timeout_seconds * 1000),
                )
            except PlaywrightTimeoutError as error:
                if blocked_targets:
                    raise blocked_targets[0] from error
                raise TimeoutError("The target did not finish rendering in time") from error
            except PlaywrightError as error:
                if blocked_targets:
                    raise blocked_targets[0] from error
                raise UpstreamRenderError("The target could not be rendered") from error

            if blocked_targets:
                raise blocked_targets[0]
            if response is None:
                raise UpstreamRenderError("The browser did not receive a page response")
            if not 200 <= response.status < 300:
                raise UpstreamHTTPError(response.status, response.status_text)
            content_type = response.headers.get("content-type", "")
            media_type = content_type.split(";", 1)[0].strip().lower()
            if media_type not in {"text/html", "application/xhtml+xml"}:
                raise UnsupportedMediaType("Only HTML and XHTML responses are supported")

            html = await page.content()
            body = html.encode("utf-8")
            if len(body) > settings.max_html_bytes:
                raise PayloadTooLarge("Rendered HTML may not exceed 1 MiB")
            return FetchedHTML(body=body, charset="utf-8", final_url=page.url)
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
        logger.warning("upstream_invalid_charset charset=%s", charset)
        return None
    return charset


def _read_html_response(response, max_bytes: int) -> bytes:
    content_type = response.getheader("Content-Type", "")
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type not in {"text/html", "application/xhtml+xml"}:
        raise UnsupportedMediaType("Only HTML and XHTML responses are supported")
    content_encoding = response.getheader("Content-Encoding", "identity").strip().lower()
    if content_encoding not in {"", "identity", "gzip", "x-gzip"}:
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
        decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            decoded = decompressor.decompress(bytes(html_bytes), max_bytes + 1)
        except zlib.error as error:
            raise UnsupportedContentEncoding("The gzip-compressed response is invalid") from error
        if len(decoded) > max_bytes or decompressor.unconsumed_tail:
            raise PayloadTooLarge("Decompressed HTML responses may not exceed 1 MiB")
        try:
            decoded += decompressor.flush(max_bytes - len(decoded) + 1)
        except zlib.error as error:
            raise UnsupportedContentEncoding("The gzip-compressed response is invalid") from error
        if len(decoded) > max_bytes:
            raise PayloadTooLarge("Decompressed HTML responses may not exceed 1 MiB")
        if not decompressor.eof or decompressor.unused_data:
            raise UnsupportedContentEncoding("The gzip-compressed response is incomplete or malformed")
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


def extract_text_result(
    html_bytes: bytes,
    max_characters: int,
    include_nav: bool = False,
    include_header: bool = False,
    include_footer: bool = False,
    from_encoding: str | None = None,
    base_url: str | None = None,
) -> ExtractedText:
    """Extract visible text from HTML bytes.

    Args:
        html_bytes: Raw HTML content.
        max_characters: Maximum number of characters to return.
        include_nav: If True, preserve <nav> elements (removed by default).
        include_header: If True, preserve <header> elements (removed by default).
        include_footer: If True, preserve <footer> elements (removed by default).
        from_encoding: Optional upstream character encoding.
        base_url: Final page URL for resolving relative links.
    """
    soup = BeautifulSoup(html_bytes, "html.parser", from_encoding=from_encoding)
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
    for node in soup.find_all(True):
        attributes = node.attrs or {}
        if "hidden" in attributes or str(attributes.get("aria-hidden") or "").lower() == "true":
            node.decompose()
            continue
        style = re.sub(r"\s+", "", str(attributes.get("style") or "").lower())
        if "display:none" in style or "visibility:hidden" in style:
            node.decompose()
            continue
        role = str(attributes.get("role") or "").lower()
        if role in {"dialog", "menu", "menuitem", "toolbar"}:
            node.decompose()
            continue
        classes = attributes.get("class", [])
        class_names = classes if isinstance(classes, list) else [classes]
        identifiers = " ".join(
            [str(attributes.get("id") or ""), *(str(value) for value in class_names)]
        )
        normalized_identifiers = re.sub(r"([a-z])([A-Z])", r"\1 \2", identifiers).lower()
        if re.search(
            r"\b(?:share|social|related|recommend(?:ation)?|advert(?:isement)?|"
            r"cookie|consent|newsletter|subscribe|breadcrumb|promo(?:tion)?|paywall)\b",
            normalized_identifiers,
        ):
            node.decompose()

    page_title = soup.title.get_text(" ", strip=True) if soup.title else ""
    if soup.title:
        soup.title.decompose()

    content_root = (
        soup.find("article")
        or soup.find("main")
        or soup.find(attrs={"role": re.compile(r"^main$", re.IGNORECASE)})
        or soup.find(
            id=re.compile(
                r"^(?:main|content|article|post|entry)(?:[-_](?:main|content|article|body))?$",
                re.IGNORECASE,
            )
        )
        or soup.find(
            class_=re.compile(
                r"^(?:main|content|article|post|entry)(?:[-_](?:main|content|article|body))?$",
                re.IGNORECASE,
            )
        )
        or soup
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
                    if all(parent is not content_root for parent in node.parents)
                )

    first_heading = content_root.find(["h1", "h2", "h3", "h4", "h5", "h6"])
    heading_text = first_heading.get_text(" ", strip=True) if first_heading else ""
    normalized_title = re.sub(r"\s+", " ", page_title).strip()
    normalized_heading = re.sub(r"\s+", " ", heading_text).strip()
    if normalized_title and normalized_title == normalized_heading:
        normalized_title = ""

    for anchor in soup.find_all("a", href=True):
        label = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True)).strip()
        href = anchor["href"].strip()
        if not label or not href or not base_url:
            continue
        resolved = urlsplit(urljoin(base_url, href))
        if resolved.scheme not in {"http", "https"} or not resolved.hostname:
            continue
        if resolved.username is not None or resolved.password is not None:
            continue
        destination = urlunsplit(
            (resolved.scheme, resolved.netloc, resolved.path, resolved.query, "")
        )
        if destination != label:
            anchor.replace_with(NavigableString(f"{label} ({destination})"))

    boundary = "\x00BINTU_BLOCK_BOUNDARY\x00"
    while boundary in " ".join(root.get_text() for root in content_roots):
        boundary += "\x00"

    for root in content_roots:
        for row in root.find_all("tr"):
            cells = row.find_all(["th", "td"], recursive=False)
            if cells:
                cell_text = [
                    re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).strip()
                    for cell in cells
                ]
                row_text = " | ".join(cell_text)
                if row.find("th", recursive=False):
                    row_text = f"{row_text}{boundary}{' | '.join('---' for _ in cells)}"
                row.replace_with(NavigableString(f"{boundary}{row_text}{boundary}"))

        for node in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
            level = int(node.name[1])
            heading = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
            node.replace_with(NavigableString(f"{boundary}{'#' * level} {heading}{boundary}"))

        for node in root.find_all(BLOCK_TAGS):
            node.insert_before(boundary)
            node.insert_after(boundary)

    text = boundary.join(root.get_text(separator=" ", strip=True) for root in content_roots)
    lines = []
    for line in text.split(boundary):
        line = re.sub(r"[\u200b\u2060\ufeff]", " ", line)
        line = re.sub(r"\s+", " ", line).strip()
        line = re.sub(r"\s+([,.;:!?])", r"\1", line)
        if line:
            lines.append(line)
    if normalized_title:
        lines.insert(0, f"# {normalized_title}")
    text = "\n".join(lines)
    if len(text) <= max_characters:
        return ExtractedText(text=text, truncated=False)
    truncated_text = text[:max_characters]
    last_boundary = max(truncated_text.rfind("\n"), truncated_text.rfind(" "))
    if last_boundary > 0:
        truncated_text = truncated_text[:last_boundary].rstrip()
    return ExtractedText(text=truncated_text, truncated=True)
