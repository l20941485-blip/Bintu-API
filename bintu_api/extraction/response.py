"""Extraction response shaping for REST and MCP surfaces.

This module centralizes the final envelope construction used after extraction,
without changing the underlying behavior or cache semantics. It preserves the
existing public JSON shape while making it easy to validate and test the
response contract in one place.
"""

from __future__ import annotations

import json
from typing import Any

from bintu_api.extraction.context import ContextResult
from bintu_api.security.url_safety import sanitize_url


def build_response_provenance(context: ContextResult) -> dict[str, Any]:
    """Return the additive provenance payload for REST/MCP compatibility."""
    provenance: dict[str, Any] = {}
    if context.request_id is not None:
        provenance["request_id"] = context.request_id
    if context.fetched_at is not None:
        provenance["fetched_at"] = context.fetched_at
    if context.requested_url is not None:
        provenance["requested_url"] = context.requested_url
    if context.final_url is not None:
        provenance["final_url"] = context.final_url
    if context.content_type is not None:
        provenance["content_type"] = context.content_type
    if context.bytes_fetched is not None:
        provenance["bytes_fetched"] = context.bytes_fetched
    if context.content_sha256 is not None:
        provenance["content_sha256"] = context.content_sha256
    if context.cache is not None:
        provenance["cache"] = {
            "hit": context.cache.hit,
            "layer": context.cache.layer,
            "age_seconds": context.cache.age_seconds,
        }
    if context.extractor_version is not None:
        provenance["extractor_version"] = context.extractor_version
    return provenance


def _mcp_selected_text(context: ContextResult) -> str:
    """Return MCP text with selected-section headings restored."""
    if context.selected_sections is None:
        return context.text
    parts = []
    for section in context.selected_sections:
        level = max(int(section.get("level", 0)), 0)
        heading = str(section.get("heading", ""))
        text = str(section.get("text", ""))
        heading_line = f"{'#' * level} {heading}".strip()
        if heading and text.startswith(heading_line):
            parts.append(text)
        else:
            parts.append(f"{heading_line}\n{text}".strip())
    return "\n\n".join(parts)


def build_mcp_envelope(
    context: ContextResult,
    source_url: str,
    *,
    restore_section_headings: bool = False,
) -> dict[str, Any]:
    """Build the public MCP structured output envelope without altering semantics."""
    provenance = build_response_provenance(context)
    safe_source_url = sanitize_url(source_url)

    envelope: dict[str, Any] = {
        "mode": context.mode,
        "tokens": context.tokens,
        "approx_tokens": context.approx_tokens,
        "html_tokens": context.html_tokens,
        "token_method": context.token_method,
        "limiting_factor": context.limiting_factor,
        "chunk_count": context.chunk_count,
        "cache_hit": context.cache_hit,
        "cache_layer": context.cache_layer,
        "source_url": safe_source_url,
        "extracted_at": context.extracted_at,
        "tokens_saved_estimate": context.tokens_saved_estimate,
        "deduplicated_count": context.deduplicated_count,
        "low_yield": context.low_yield,
        **({"yield_hint": context.yield_hint} if context.low_yield else {}),
        "text": (
            _mcp_selected_text(context)
            if restore_section_headings
            else context.text
        ),
        "truncated": context.truncated,
        **(
            {"selected_sections": context.selected_sections}
            if context.selected_sections is not None
            else {}
        ),
        "split": context.split,
        "chunks": context.chunks,
        **provenance,
    }
    return envelope


def build_rest_response(context: ContextResult, source_url: str) -> dict[str, Any]:
    """Build the REST response dict while keeping the existing output shape."""
    provenance = build_response_provenance(context)
    safe_source_url = sanitize_url(source_url)
    return {
        "url": safe_source_url,
        "text": context.text,
        "truncated": context.truncated,
        "cache_hit": context.cache_hit,
        "cache_layer": context.cache_layer,
        "approx_tokens": context.approx_tokens,
        "token_method": context.token_method,
        "tokens": context.tokens,
        "tokens_saved_estimate": context.tokens_saved_estimate,
        "low_yield": context.low_yield,
        **({"yield_hint": context.yield_hint} if context.low_yield else {}),
        **(
            {"selected_sections": context.selected_sections}
            if context.selected_sections is not None
            else {}
        ),
        "provenance": provenance,
    }


def build_mcp_text_payload(envelope: dict[str, Any]) -> str:
    """Serialize the MCP envelope exactly as the existing endpoint does."""
    return json.dumps(envelope)


