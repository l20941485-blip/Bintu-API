"""HTML-to-text extraction for Bintu.

This module owns the BeautifulSoup-based extraction pipeline: content-root
selection, noise/boilerplate removal, link handling, table/heading/pre-block
serialization, and truncation. It imports shared text-cleaning helpers from
``bintu_api.extraction.cleaner`` and performs no network access.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, NavigableString, Tag

from bintu_api.extraction.cleaner import (
    close_up_punctuation,
    drop_empty_fences,
    same_document,
    should_drop_title,
    strip_permalinks,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExtractedText:
    text: str
    truncated: bool


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


def _unwrap_inline_with_space(node) -> None:
    """Unwrap an inline node while preserving word boundaries."""
    parent = node.parent
    if parent is None:
        return

    previous = node.previous_sibling
    next_sibling = node.next_sibling

    needs_leading_space = (
        previous is not None
        and isinstance(previous, NavigableString)
        and previous.string
        and not previous.string[-1:].isspace()
    )

    needs_trailing_space = (
        next_sibling is not None
        and isinstance(next_sibling, NavigableString)
        and next_sibling.string
        and not next_sibling.string[:1].isspace()
    )

    node.unwrap()

    if needs_leading_space:
        parent.insert(0, NavigableString(" "))

    if needs_trailing_space:
        parent.append(NavigableString(" "))


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
    """Select discussion content for comment-thread pages."""
    comment_nodes = soup.select(
        "div.commtext, span.commtext, td.comment, [class*='comment-body'],[data-testid*='comment']"
    )

    if not comment_nodes:
        return None

    thread_root = soup.new_tag("div")
    thread_root["class"] = "bintu-comment-thread"

    title_anchor = soup.select_one("a.titlelink, .titleline a, .storylink")
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
    """Select a root containing a meaningful share of visible page text."""
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


def _footnote_destination_key(destination: str) -> str:
    parts = urlsplit(destination)
    hostname = parts.hostname

    if hostname is None:
        return destination

    try:
        port = parts.port
    except ValueError:
        return destination

    host = f"[{hostname.lower()}]" if ":" in hostname else hostname.lower()
    if port is not None and not (
        (parts.scheme.lower() == "http" and port == 80)
        or (parts.scheme.lower() == "https" and port == 443)
    ):
        host = f"{host}:{port}"

    path = parts.path[:-1] if parts.path.endswith("/") else parts.path
    return urlunsplit((parts.scheme.lower(), host, path, parts.query, ""))


def _footnote_display_label(destination: str, max_length: int) -> str:
    parts = urlsplit(destination)
    hostname = parts.hostname

    if hostname is None:
        label = destination
    else:
        host = f"[{hostname.lower()}]" if ":" in hostname else hostname.lower()
        try:
            port = parts.port
        except ValueError:
            port = None

        if port is not None and not (
            (parts.scheme.lower() == "http" and port == 80)
            or (parts.scheme.lower() == "https" and port == 443)
        ):
            host = f"{host}:{port}"

        label = f"{host}{parts.path}"
        if parts.query:
            label = f"{label}?{parts.query}"

    if len(label) <= max_length:
        return label
    if max_length == 1:
        return "â€¦"
    return f"{label[: max_length - 1]}â€¦"


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
        shielded = code.replace("\u00a0", " ").replace("\n", PRE_NL).replace(" ", PRE_SP).replace("\t", PRE_TAB)
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

    limit = max_characters - 4 if "```" in text else max_characters
    truncated_text = text[:limit]

    last_boundary = max(
        truncated_text.rfind("\n"),
        truncated_text.rfind(" "),
    )

    if last_boundary > 0:
        truncated_text = truncated_text[:last_boundary].rstrip()

    truncated_text = drop_empty_fences(close_open_fence(truncated_text))

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
        line = close_up_punctuation(line)
        if line:
            lines.append(line)

    return "\n".join(lines)


def _ensure_space_before(node) -> None:
    """Ensure a word boundary exists immediately before this node."""
    previous = node.previous_sibling

    if previous is None:
        return

    if isinstance(previous, NavigableString):
        if previous.string and not previous.string.endswith((" ", "\n", "\t")):
            previous.replace_with(NavigableString(f"{previous.string} "))
        return

    if isinstance(previous, Tag):
        children = list(previous.children)
        last_child = children[-1] if children else None

        if (
            isinstance(last_child, NavigableString)
            and last_child.string
            and not last_child.string.endswith((" ", "\n", "\t"))
        ):
            last_child.replace_with(NavigableString(f"{last_child.string} "))


def extract_text_result(
    html_bytes: bytes,
    max_characters: int,
    include_nav: bool = False,
    include_header: bool = False,
    include_footer: bool = False,
    from_encoding: str | None = None,
    base_url: str | None = None,
    links: str = "inline",
    footnote_url_policy: Literal["full", "truncated"] = "truncated",
    max_footnote_url_length: int | None = None,
    footnote_display_max_length: int | None = None,
) -> ExtractedText:
    """Extract text; footnote URL length defaults to 100 and supports a deprecated alias."""
    if links not in {"inline", "footnotes", "false"}:
        raise ValueError("links must be one of: inline, footnotes, false")
    if links == "footnotes" and footnote_url_policy not in {"full", "truncated"}:
        raise ValueError("footnote_url_policy must be 'full' or 'truncated'")
    if (
        footnote_display_max_length is not None
        and max_footnote_url_length is not None
        and footnote_display_max_length != max_footnote_url_length
    ):
        raise ValueError(
            "Specify either max_footnote_url_length or "
            "footnote_display_max_length, not both"
        )
    if max_footnote_url_length is None:
        max_footnote_url_length = (
            footnote_display_max_length
            if footnote_display_max_length is not None
            else 100
        )
    if links == "footnotes" and max_footnote_url_length < 1:
        raise ValueError("max_footnote_url_length must be greater than zero")

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

    for edit_section in soup.find_all(class_="mw-editsection"):
        edit_section.decompose()

    strip_permalinks(soup)

    for node in soup.find_all(True):
        attributes = node.attrs or {}

        if "hidden" in attributes or str(attributes.get("aria-hidden") or "").lower() == "true":
            node.decompose()
            continue

        style = re.sub(
            r"\s+",
            "",
            str(attributes.get("style") or "").lower(),
        )
        if "display:none" in style or "visibility:hidden" in style:
            node.decompose()
            continue

        role = str(attributes.get("role") or "").lower()
        if role in {
            "dialog",
            "menu",
            "menuitem",
            "toolbar",
        }:
            node.decompose()
            continue

        classes = attributes.get("class", [])
        class_names = classes if isinstance(classes, list) else [classes]
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

    page_title = soup.title.get_text(" ", strip=True) if soup.title else ""
    if soup.title:
        soup.title.decompose()

    comment_thread_root = _select_comment_thread_root(soup)

    content_root = comment_thread_root or _pick_content_root(soup)

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

    if normalized_title and should_drop_title(normalized_title, normalized_heading):
        normalized_title = ""

    footnotes: list[str] = []
    footnote_numbers: dict[str, int] = {}

    seen_anchors: set[int] = set()
    content_anchors: list[Tag] = []

    for root in content_roots:
        for anchor in root.find_all("a", href=True):
            anchor_id = id(anchor)
            if anchor_id not in seen_anchors:
                seen_anchors.add(anchor_id)
                content_anchors.append(anchor)

    for anchor in content_anchors:
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

        href_parts = urlsplit(href)
        original_destination = (
            href if href_parts.scheme and href_parts.netloc else urljoin(base_url, href)
        )
        resolved = urlsplit(original_destination)

        if resolved.scheme not in {"http", "https"} or not resolved.hostname:
            continue

        if resolved.username is not None or resolved.password is not None:
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

        if links == "false":
            anchor.replace_with(NavigableString(f" {label} "))
            continue

        if links == "footnotes":
            key = _footnote_destination_key(original_destination)
            number = footnote_numbers.get(key)
            if number is None:
                number = len(footnotes) + 1
                footnote_numbers[key] = number
                footnotes.append(original_destination)
            anchor.replace_with(NavigableString(f" {label} [{number}] "))
            continue

        if same_document(base_url, resolved):
            _unwrap_inline_with_space(anchor)
            continue

        if destination != label:
            if anchor.find(list(BLOCK_TAGS)):
                anchor.append(NavigableString(f" ({destination})"))
                _unwrap_inline_with_space(anchor)
            else:
                anchor.replace_with(NavigableString(f" {label} ({destination}) "))
            continue

        _unwrap_inline_with_space(anchor)

    boundary = "\x00BINTU_BLOCK_BOUNDARY\x00"

    while boundary in " ".join(root.get_text() for root in content_roots):
        boundary += "\x00"

    for root in content_roots:
        protect_pre_blocks(root, boundary)

        for row in reversed(root.find_all("tr")):
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
                    row_text = f"{row_text}{boundary}{' | '.join('---' for _ in cells)}"

                row.replace_with(NavigableString(f"{boundary}{row_text}{boundary}"))

        for node in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
            level = int(node.name[1])
            heading = re.sub(
                r"\s+",
                " ",
                node.get_text(" ", strip=True),
            ).strip()
            node.replace_with(NavigableString(f"{boundary}{'#' * level} {heading}{boundary}"))

        for node in root.find_all(BLOCK_TAGS):
            node.insert_before(boundary)
            node.insert_after(boundary)

    text = boundary.join(root.get_text() for root in content_roots)

    lines = []

    for line in text.split(boundary):
        line = re.sub(
            r"[\u200b\u2060\ufeff]",
            " ",
            line,
        )
        line = re.sub(r"\s+", " ", line).strip()
        line = close_up_punctuation(line)

        if line:
            lines.append(line)

    if normalized_title:
        lines.insert(0, f"# {normalized_title}")

    if links == "footnotes" and footnotes:
        footnote_lines = []
        for index, destination in enumerate(footnotes, start=1):
            display_label = _footnote_display_label(
                destination,
                max_footnote_url_length,
            )
            escaped_label = (
                display_label.replace("\\", "\\\\")
                .replace("[", "\\[")
                .replace("]", "\\]")
            )
            if (
                footnote_url_policy == "truncated"
                and len(destination) > max_footnote_url_length
            ):
                footnote_lines.append(
                    f"{index}. {escaped_label} [URL truncated]"
                )
            else:
                footnote_lines.append(
                    f"{index}. [{escaped_label}](<{destination}>)"
                )
        lines.extend(["", "## Links"])
        lines.extend(footnote_lines)

    text = "\n".join(lines)
    text = restore_pre_placeholders(text)

    bs4_text = text.strip()

    fallback_text = None
    if len(bs4_text) == 0 and comment_thread_root is None:
        fallback_text = _trafilatura_fallback(
            html_bytes,
            max_characters,
            from_encoding,
            base_url,
        )

    if fallback_text and len(fallback_text.strip()) >= len(bs4_text) + 80:
        if normalized_title:
            fallback_text = f"# {normalized_title}\n{fallback_text}"

        return _truncate_extracted_text(
            fallback_text,
            max_characters,
        )

    return _truncate_extracted_text(
        text,
        max_characters,
    )

