"""MCP-compatible tool discovery and invocation helpers.


Two surfaces intentionally share the same tool definitions:


- /mcp/tools and /mcp/tools/call are legacy JSON helper endpoints.
- /mcp is the standard stateless Streamable HTTP endpoint implemented in
  bintu_api.mcp.streamable.


Successful tool calls expose the extraction envelope as structuredContent
and preserve its JSON representation in content[0].text.
"""

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Security
from pydantic import ValidationError

from bintu_api.auth import (
    api_key_scheme,
    mcp_rate_limit_identity,
    verify_mcp_api_access,
)
from bintu_api.context import (
    _decode_source_text,
)
from bintu_api.extraction.cache import build_cache_economics
from bintu_api.extraction.service import fetch_and_extract as routes_common_fetch_and_extract
from bintu_api.mcp.schemas import (
    TOOL_ANNOTATIONS as _TOOL_ANNOTATIONS,
)
from bintu_api.mcp.schemas import (
    TOOL_DESCRIPTION as _TOOL_DESCRIPTION,
)
from bintu_api.mcp.schemas import (
    TOOL_INPUT_SCHEMA as _TOOL_INPUT_SCHEMA,
)
from bintu_api.mcp.schemas import (
    TOOL_NAME as _TOOL_NAME,
)
from bintu_api.mcp.schemas import (
    TOOL_OUTPUT_SCHEMA as _TOOL_OUTPUT_SCHEMA,
)
from bintu_api.mcp.schemas import (
    TOOL_TITLE as _TOOL_TITLE,
)
from bintu_api.mcp.tools import ToolArguments, ToolCallRequest
from bintu_api.mcp_descriptions import (
    CACHE_DESCRIPTION,
    MAX_TOKENS_DESCRIPTION,
    MODE_DESCRIPTION,
    OUTPUT_SCHEMA_EXTRA_PROPERTIES,
    PERSIST_DESCRIPTION,
    RENDER_JS_DESCRIPTION,
    URL_DESCRIPTION,
)
from bintu_api.mcp_descriptions import (
    TOOL_DESCRIPTION as NEW_TOOL_DESCRIPTION,
)
from bintu_api.observability import log_extraction_completed
from bintu_api.scraper import TargetURLRejected
from bintu_api.settings import Settings

router = APIRouter(prefix="/mcp", tags=["MCP"])


logger = logging.getLogger("bintu_api.mcp")


TOOL_NAME = "bintu_scrape_text"
TOOL_TITLE = "Bintu Scrape Text"


TOOL_DESCRIPTION = NEW_TOOL_DESCRIPTION


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
                "Absolute public HTTP or HTTPS URL to extract. Unsafe targets fail with invalid_or_unsafe_url."
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
        "links": {
            "type": "string",
            "enum": ["inline", "footnotes", "false"],
            "default": "inline",
            "description": (
                "How to represent hyperlinks in extracted text. "
                "inline preserves readable link URLs; footnotes uses "
                "numbered references and a link list; false removes "
                "URLs for the lowest-token output."
            ),
        },
        "footnote_url_policy": {
            "type": "string",
            "enum": ["full", "truncated"],
            "default": "truncated",
            "description": (
                "For links=footnotes only, choose full URL destinations or "
                "replace over-limit destinations with non-clickable truncated text."
            ),
        },
        "max_footnote_url_length": {
            "type": "integer",
            "minimum": 1,
            "default": 100,
            "description": (
                "For links=footnotes only, maximum URL length for the visible "
                "label and truncated destination."
            ),
        },
        "mode": {
            "type": "string",
            "enum": ["scrape", "chunk", "summarize", "chunked"],
            "default": "scrape",
            "description": (
                "scrape returns extracted text in the envelope; chunk "
                "creates approximately budgeted chunks; summarize "
                "selects leading sentences within an approximate budget. "
                "The accepted chunked alias normalizes to chunk."
            ),
        },
        "chunk_token_budget": {
            "type": "integer",
            "minimum": 100,
            "maximum": 50000,
            "description": ("Accepted alias for max_tokens; max_tokens wins on conflict."),
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
        "persist": {
            "type": "boolean",
            "default": True,
            "description": (
                "Allow a fresh successful result to be written to the "
                "persistent cache. False prevents that write; memory "
                "caching and extraction are unchanged."
            ),
        },
    },
    "required": ["url"],
    "additionalProperties": False,
}


TOOL_INPUT_SCHEMA["properties"]["url"]["description"] = URL_DESCRIPTION
TOOL_INPUT_SCHEMA["properties"]["mode"]["description"] = MODE_DESCRIPTION
TOOL_INPUT_SCHEMA["properties"]["max_tokens"]["description"] = MAX_TOKENS_DESCRIPTION
TOOL_INPUT_SCHEMA["properties"]["cache"]["description"] = CACHE_DESCRIPTION
TOOL_INPUT_SCHEMA["properties"]["persist"]["description"] = PERSIST_DESCRIPTION
TOOL_INPUT_SCHEMA["properties"]["render_js"]["description"] = RENDER_JS_DESCRIPTION
TOOL_OUTPUT_SCHEMA["properties"].update(OUTPUT_SCHEMA_EXTRA_PROPERTIES)


TOOL_ANNOTATIONS = _TOOL_ANNOTATIONS
TOOL_DESCRIPTION = _TOOL_DESCRIPTION
TOOL_INPUT_SCHEMA = _TOOL_INPUT_SCHEMA
TOOL_NAME = _TOOL_NAME
TOOL_OUTPUT_SCHEMA = _TOOL_OUTPUT_SCHEMA
TOOL_TITLE = _TOOL_TITLE


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


@router.get("/tools")
async def list_tools(request: Request) -> dict[str, Any]:
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
            detail={
                "code": "unknown_tool",
                "message": f"Unknown MCP tool: {payload.name}.",
                "hint": f"Use the supported tool: {TOOL_NAME}.",
            },
        )

    try:
        arguments = ToolArguments.model_validate(payload.arguments)
    except ValidationError as error:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_tool_arguments",
                "message": "The tool arguments are invalid.",
                "hint": "Check the tool input schema and retry.",
                "errors": error.errors(),
            },
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

    sections = arguments.sections

    try:
        document, cached, cache_layer = await routes_common_fetch_and_extract(
            request,
            arguments.url,
            include_nav=False,
            include_header=False,
            include_footer=False,
            render_js=arguments.render_js,
            skip_cache=not arguments.cache,
            persist=arguments.persist,
            max_tokens=arguments.max_tokens,
            links=arguments.links,
            footnote_url_policy=arguments.footnote_url_policy,
            max_footnote_url_length=arguments.max_footnote_url_length,
            )

    except TargetURLRejected as error:
        return _mcp_error_response(
            "invalid_or_unsafe_url",
            str(error),
            "URL must start with http:// or https:// and be publicly accessible.",
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

    cache_economics = build_cache_economics(document, cached, cache_layer)

    from bintu_api.extraction.pipeline import run_extraction

    context = await run_extraction(
        request,
        arguments.url,
        mode=arguments.mode,
        max_tokens=arguments.max_tokens,
        sections=sections,
        cache=arguments.cache,
        render_js=arguments.render_js,
        include_nav=False,
        include_header=False,
        include_footer=False,
        identity=mcp_rate_limit_identity(request, settings),
        raw_text=cached.markdown,
        content_truncated=cached.truncated,
        html_source_text=(_decode_source_text(document) if document is not None else ""),
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

    from bintu_api.extraction.response import build_mcp_envelope

    envelope = build_mcp_envelope(context, arguments.url)

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


