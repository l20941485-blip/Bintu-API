import codecs
import http.client
import ipaddress
import logging
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
USER_AGENT = "BintuAPI/1.0 (+https://rapidapi.com; public web text extraction)"
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


def fetch_html_document(url: str, settings: Settings) -> FetchedHTML:
    """Fetch a public HTML page, following redirects and re-validating every hop.

    Each hop performs a fresh DNS resolution and pins the connection to a
    validated public address, so a public hostname can never redirect the
    request into a private network (DNS rebinding included).
    """
    current_url = url
    for _ in range(settings.max_redirects + 1):
        parsed, host, port, path = _parse_target(current_url)
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
