"""Legacy compatibility module for context chunking and summarization.

New code should import from ``bintu_api.extraction.chunker`` and
``bintu_api.extraction.summarizer``. This module remains so existing imports
and compatibility expectations continue to work.
"""

from bintu_api.extraction.chunker import (
    apply_link_policy,
    sentence_pieces,
    split_block,
    split_code_body,
    split_into_chunks,
    split_long_line,
    split_prose_block,
)
from bintu_api.extraction.summarizer import summarize_text

__all__ = [
    "apply_link_policy",
    "sentence_pieces",
    "split_block",
    "split_code_body",
    "split_into_chunks",
    "split_long_line",
    "split_prose_block",
    "summarize_text",
]
