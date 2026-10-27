"""Extract retained reader documents without changing scrape limits."""

from bintu_api.reader import (
    DEFAULT_MAX_DOCUMENT_CHARACTERS,
    DocumentSnapshot,
)
from bintu_api.scraper import FetchedHTML, extract_text_result


class ReaderDocumentTooLarge(ValueError):
    """Extracted text exceeds the reader's retention limit."""


class ReaderDocumentEmpty(ValueError):
    """No readable text was extracted."""


def snapshot_from_document(
    document: FetchedHTML,
    *,
    requested_url: str,
    include_nav: bool = False,
    include_header: bool = False,
    include_footer: bool = False,
) -> DocumentSnapshot:
    """Extract a bounded snapshot from an already-fetched document.

    This function performs no network requests, cache access, authentication,
    or usage accounting. The caller must enforce those boundaries.
    Oversized extraction is rejected rather than silently shortened.
    """
    extracted = extract_text_result(
        document.body,
        DEFAULT_MAX_DOCUMENT_CHARACTERS + 1,
        include_nav=include_nav,
        include_header=include_header,
        include_footer=include_footer,
        from_encoding=document.charset,
        base_url=document.final_url or requested_url,
    )

    if (
        extracted.truncated
        or len(extracted.text) > DEFAULT_MAX_DOCUMENT_CHARACTERS
    ):
        raise ReaderDocumentTooLarge(
            "Extracted document exceeds the reader character limit."
        )

    if not extracted.text.strip():
        raise ReaderDocumentEmpty("No readable text was extracted.")

    return DocumentSnapshot(extracted.text)
