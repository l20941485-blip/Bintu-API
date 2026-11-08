"""Legacy compatibility module for the context extraction pipeline.

New code should import from ``bintu_api.extraction.context``. This module
preserves the historical ``bintu_api.context`` import paths and the
``bintu_api.context.rate_limit_identity`` patch target used by tests.
"""

from bintu_api.auth import rate_limit_identity
from bintu_api.extraction.context import (
    DEFAULT_MAX_TEXT_CHARACTERS,
    MAX_EXTRACTION_CHARACTERS,
    TOKEN_METHOD,
    CacheEconomics,
    ContextMode,
    ContextResult,
    _decode_source_text,
    _is_table_block,
    _sentences,
    count_tokens,
    delivered_savings,
    extract_context,
    normalize_mode,
    resolve_effective_char_cap,
    split_into_chunks,
    summarize_text,
)

__all__ = [
    "DEFAULT_MAX_TEXT_CHARACTERS",
    "MAX_EXTRACTION_CHARACTERS",
    "TOKEN_METHOD",
    "CacheEconomics",
    "ContextMode",
    "ContextResult",
    "count_tokens",
    "delivered_savings",
    "extract_context",
    "normalize_mode",
    "rate_limit_identity",
    "resolve_effective_char_cap",
    "split_into_chunks",
    "summarize_text",
    "_decode_source_text",
    "_is_table_block",
    "_sentences",
]
