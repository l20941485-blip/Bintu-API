"""MCP-compatible tool discovery and invocation helpers.

Two surfaces intentionally share the same tool definitions:

- /mcp/tools and /mcp/tools/call are legacy JSON helper endpoints.
- /mcp is the standard stateless Streamable HTTP endpoint implemented in
  bintu_api.mcp_streamable.

Successful tool calls expose the extraction envelope as structuredContent
and preserve its JSON representation in content[0].text.
"""

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Security
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from bintu_api import routes
from bintu_api.auth import (
    api_key_scheme,
    mcp_rate_limit_identity,
    verify_mcp_api_access,
)
from bintu_api.context import (
    CacheEconomics,
    _decode_source_text,
    extract_context,
    normalize_mode,
)
from bintu_api.observability import log_extraction_completed
from bintu_api.scraper import TargetURLRejected
from bintu_api.settings import Settings


router = APIRouter(prefix="/mcp", tags=["MCP"])

logger = logging.getLogger("bintu_api.mcp")

TOOL_NAME = "bintu_scrape_text"
TOOL_TITLE = "Bintu Scrape Text"

TOOL_DESCRIPTION = (
    "Fetch one public absolute HTTP or HTTPS URL and extract readable text. "
    "Only HTML/XHTML is supported, with a 1 MiB decoded-body limit and "
    "extracted text capped at 6,000 characters. Article/main content is "
    "preferred and common page furniture is omitted. "
    "Default mode=scrape returns the extraction envelope. "
    "Use mode=chunk (accepted alias: chunked) for approximately budgeted "
    "chunks, or mode=summarize for sentence-based truncation. "
    "Chunking preserves words, URLs, and recognized table rows; an intact "
    "URL, word, or table row may exceed max_tokens. Whitespace can be "
    "normalized during chunking. "
    "tokens and approx_tokens are character-based sizing estimates, not "
    "tokenizer counts or exact billing measurements. "
    "tokens_saved_estimate compares source HTML and delivered text estimates "
    "when the baseline is available; cached results may preserve the original "
    "extraction economics. Savings are not limited to summarize mode. "
    "truncated reports content truncation; split reports multiple chunks. "
    "The character cap applies before mode transformation. max_tokens is "
    "ignored in scrape mode. "
    "Set cache=false to bypass cache reads; successful fresh results may "
    "still be written to cache. "
    "JavaScript rendering is available only when enabled by the operator. "
    "If render_js_disabled is returned, retry with render_js=false. "
    "Execution failures are reported in-band with isError=true."
)

TOOL_ANNOTATIONS = {
    "title": TOOL_TITLE,
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}

TOOL_OUTPUT_SCHEMA = {
    "type": "object",
    "description": (
        "Successful extraction envelope returned in structuredContent. "
        "The same object is serialized as JSON in content[0].text."
    ),
    "properties": {
        "mode": {
            "type": "string",
            "enum": ["scrape", "chunk", "summarize"],
        },
        "tokens": {
            "type": "integer",
            "minimum": 0,
            "description": "Compatibility alias of approx_tokens.",
        },
        "approx_tokens": {
            "type": "integer",
            "minimum": 0,
        },
        "html_tokens": {
            "type": "integer",
            "minimum": 0,
        },
        "token_method": {
            "type": "string",
        },
        "limiting_factor": {
            "type": "string",
        },
        "chunk_count": {
            "type": "integer",
            "minimum": 0,
        },
        "cache_hit": {
            "type": "boolean",
        },
        "cache_layer": {
            "type": "string",
        },
        "source_url": {
            "type": "string",
        },
        "extracted_at": {
            "type": "string",
        },
        "tokens_saved_estimate": {
            "type": "integer",
            "minimum": 0,
        },
        "truncated": {
            "type": "boolean",
        },
        "split": {
            "type": "boolean",
        },
        "chunks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {
                        "type": "integer",
                        "minimum": 0,
                    },
                    "text": {
                        "type": "string",
                    },
                    "tokens": {
                        "type": "integer",
                        "minimum": 0,
                    },
                    "approx_tokens": {
                        "type": "integer",
                        "minimum": 0,
                    },
                },
                "required": [
                    "index",
                    "text",
                    "tokens",
                    "approx_tokens",
                ],
                "additionalProperties": True,
            },
        },
    },
    "required": [
        "mode",
        "tokens",
        "approx_tokens",
        "html_tokens",
        "token_method",
        "limiting_factor",
        "chunk_count",
        "cache_hit",
        "cache_layer",
        "source_url",
        "extracted_at",
        "tokens_saved_estimate",
        "truncated",
        "split",
        "chunks",
    ],
    # Allow additive provenance without changing the core contract.
    "additionalProperties": True,
}

TOOL_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "format": "uri",
            "description": (
                "Absolute public HTTP or HTTPS URL to extract. "
                "Unsafe targets fail with invalid_or_unsafe_url."
            ),
            "examples": [
                "https://www.iana.org/domains/reserved",
            ],
        },
        "render_js": {
            "type": "boolean",
            "default": False,
            "description": (
                "Render in Chromium before extraction when enabled by "
                "the operator. If render_js_disabled is returned, retry "
                "with false."
            ),
        },
        "mode": {
            "type": "string",
            "enum": ["scrape", "chunk", "summarize"],
            "default": "scrape",
            "description": (
                "scrape returns extracted text in the envelope; chunk "
                "creates approximately budgeted chunks; summarize "
                "selects leading sentences within an approximate budget. "
                "The accepted chunked alias normalizes to chunk."
            ),
        },
        "max_tokens": {
            "type": "integer",
            "default": 6000,
            "minimum": 100,
            "maximum": 50000,
            "description": (
                "Approximate token budget for chunk/summarize modes; "
                "ignored in scrape mode. Accepted alias: "
                "chunk_token_budget. The extracted-text character cap "
                "applies first. Indivisible units in chunk mode, and a "
                "first oversized sentence in summarize mode, may exceed "
                "the budget."
            ),
        },
        "cache": {
            "type": "boolean",
            "default": True,
            "description": (
                "Read available memory/persistent caches. False bypasses "
                "cache reads but does not disable writes of fresh results."
            ),
        },
    },
    "required": ["url"],
    "additionalProperties": False,
}


class ToolCallRequest(BaseModel):
    name: str
    arguments: dict[str, Any]


class ToolArguments(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
    )

    url: str
    render_js: bool = False
    mode: str = "scrape"
    max_tokens: int = Field(
        default=6000,
        ge=100,
        le=50000,
    )
    cache: bool = True

    @model_validator(mode="before")
    @classmethod
    def _normalize_aliases(cls, data: Any) -> Any:
        """Normalize aliases while preserving canonical argument priority."""
        if not isinstance(data, dict):
            return data

        normalized = dict(data)

        if "mode" in normalized:
            normalized["mode"] = normalize_mode(normalized["mode"])

        if "chunk_token_budget" in normalized:
            if "max_tokens" in normalized:
                logger.warning(
                    "mcp_alias_conflict canonical=max_tokens wins "
                    "over chunk_token_budget"
                )
                normalized.pop("chunk_token_budget")
            else:
                normalized["max_tokens"] = normalized.pop(
                    "chunk_token_budget"
                )

        max_tokens = normalized.get("max_tokens", 6000)
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int):
            raise ValueError("max_tokens must be an integer")

        return normalized


def _mcp_error_response(
    code: str,
    message: str,
    hint: str,
) -> dict[str, Any]:
    """Return a stable in-band tool error."""
    logger.info("mcp_tool_error code=%s", code)
    return {
        "content": [
            {
                "type": "text",
                "text": f"{code}: {message} {hint}".strip(),
            }
        ],
        "isError": True,
    }


@router.get(
    "/tools",
    dependencies=[Security(api_key_scheme, scopes=[])],
)
async def list_tools(request: Request) -> dict[str, Any]:
    verify_mcp_api_access(request, request.app.state.settings)
    return {
        "tools": [
            {
                "name": TOOL_NAME,
                "title": TOOL_TITLE,
                "description": TOOL_DESCRIPTION,
                "inputSchema": TOOL_INPUT_SCHEMA,
                "outputSchema": TOOL_OUTPUT_SCHEMA,
                "annotations": TOOL_ANNOTATIONS,
            }
        ]
    }


@router.post(
    "/tools/call",
    dependencies=[Security(api_key_scheme, scopes=[])],
)
async def call_tool(
    payload: ToolCallRequest,
    request: Request,
) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    verify_mcp_api_access(request, settings)

    if payload.name != TOOL_NAME:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown MCP tool: {payload.name}",
        )

    try:
        arguments = ToolArguments.model_validate(payload.arguments)
    except ValidationError as error:
        raise HTTPException(
            status_code=400,
            detail=error.errors(),
        ) from error

    if arguments.render_js and not settings.render_js_enabled:
        return _mcp_error_response(
            "render_js_disabled",
            "JavaScript rendering is disabled on this service.",
            "Retry with render_js=false for plain HTML extraction.",
        )

    await asyncio.to_thread(
        request.app.state.rate_limiter.check,
        mcp_rate_limit_identity(request, settings),
    )

    try:
        document, cached, cache_layer = await routes._fetch_and_extract(
            request,
            arguments.url,
            include_nav=False,
            include_header=False,
            include_footer=False,
            render_js=arguments.render_js,
            skip_cache=not arguments.cache,
        )
    except TargetURLRejected as error:
        return _mcp_error_response(
            "invalid_or_unsafe_url",
            str(error),
            "URL must start with http:// or https:// and be "
            "publicly accessible.",
        )
    except HTTPException as error:
        detail = error.detail
        if isinstance(detail, dict) and isinstance(
            detail.get("code"),
            str,
        ):
            return _mcp_error_response(
                detail["code"],
                str(detail.get("message", "Extraction failed.")),
                str(detail.get("hint", "")).strip(),
            )
        raise

    cache_economics = None
    if cache_layer == "persistent":
        cache_economics = CacheEconomics(
            html_tokens=cached.html_tokens,
            tokens_saved_estimate=cached.tokens_saved_estimate,
            limiting_factor=cached.limiting_factor,
            truncated=cached.truncated,
            extracted_at=cached.extracted_at,
        )

    context = await extract_context(
        request,
        arguments.url,
        mode=arguments.mode,
        max_tokens=arguments.max_tokens,
        cache=arguments.cache,
        render_js=arguments.render_js,
        include_nav=False,
        include_header=False,
        include_footer=False,
        identity=mcp_rate_limit_identity(request, settings),
        raw_text=cached.markdown,
        content_truncated=cached.truncated,
        html_source_text=(
            _decode_source_text(document)
            if document is not None
            else ""
        ),
        cache_hit=cache_layer != "none",
        cache_layer=cache_layer,
        document=document,
        settings=settings,
        cache_economics=cache_economics,
        extracted_at=cached.extracted_at,
    )

    log_extraction_completed(
        request_id=getattr(
            getattr(request, "state", None),
            "request_id",
            None,
        ),
        url=arguments.url,
        mode=context.mode,
        cache_hit=context.cache_hit,
        cache_layer=context.cache_layer,
        approx_tokens=context.approx_tokens,
        html_tokens=context.html_tokens,
        tokens_saved_estimate=context.tokens_saved_estimate,
        truncated=context.truncated,
        limiting_factor=context.limiting_factor,
    )

    envelope = {
        "mode": context.mode,
        "tokens": context.tokens,
        "approx_tokens": context.approx_tokens,
        "html_tokens": context.html_tokens,
        "token_method": context.token_method,
        "limiting_factor": context.limiting_factor,
        "chunk_count": context.chunk_count,
        "cache_hit": context.cache_hit,
        "cache_layer": context.cache_layer,
        "source_url": routes.sanitize_url(arguments.url),
        "extracted_at": context.extracted_at,
        "tokens_saved_estimate": context.tokens_saved_estimate,
        "truncated": context.truncated,
        "split": context.split,
        "chunks": context.chunks,
    }

    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(envelope),
            }
        ],
        "structuredContent": envelope,
        "isError": False,
    }