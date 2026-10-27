"""Local lossless paging with an approximate content-only token budget."""

from dataclasses import dataclass

from bintu_api.context import TOKEN_METHOD, count_tokens


DEFAULT_MAX_DOCUMENT_CHARACTERS = 200_000


def _require_integer(name: str, value: int, minimum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer.")
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}.")


@dataclass(frozen=True)
class DocumentSnapshot:
    """Retained text, independent of response-page limits."""

    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise ValueError("text must be a string.")
        if len(self.text) > DEFAULT_MAX_DOCUMENT_CHARACTERS:
            raise ValueError(
                "Document exceeds the retained-document character limit."
            )


@dataclass(frozen=True)
class DocumentPage:
    text: str
    start_offset: int
    end_offset: int
    next_offset: int | None
    has_more: bool
    approx_tokens: int
    token_method: str
    boundary_split: bool


def read_page(
    snapshot: DocumentSnapshot,
    *,
    max_tokens: int,
    offset: int = 0,
) -> DocumentPage:
    """Read an exact slice within the approximate text budget.

    Offsets count Python string characters, not bytes or model tokens.
    They are internal positions, not authenticated public cursors.
    Sequential pages reconstruct the snapshot, including whitespace.

    Prefer whitespace in the latter half of the available window.
    Otherwise split at the hard character limit, including inside URLs
    or table rows. Existing chunk-mode behavior is unaffected.
    """
    _require_integer("max_tokens", max_tokens, 1)
    _require_integer("offset", offset, 0)

    text = snapshot.text
    if offset > len(text):
        raise ValueError("offset exceeds the document length.")

    end = min(len(text), offset + max_tokens * 4)

    if end < len(text):
        minimum_end = offset + max(1, (end - offset) // 2)
        for candidate in range(end, minimum_end - 1, -1):
            if text[candidate - 1].isspace() or text[candidate].isspace():
                end = candidate
                break

    page_text = text[offset:end]
    has_more = end < len(text)
    boundary_split = (
        has_more
        and end > offset
        and not text[end - 1].isspace()
        and not text[end].isspace()
    )

    return DocumentPage(
        text=page_text,
        start_offset=offset,
        end_offset=end,
        next_offset=end if has_more else None,
        has_more=has_more,
        approx_tokens=count_tokens(page_text),
        token_method=TOKEN_METHOD,
        boundary_split=boundary_split,
    )
