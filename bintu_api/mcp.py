"""Simple MCP-compatible tool discovery and invocation endpoints.


Two surfaces exist on purpose:


- ``/mcp/tools`` and ``/mcp/tools/call``: minimal JSON helpers with the same
  shapes as MCP content blocks; kept for the existing RapidAPI listing and
  any integrations written against them.
- ``/mcp`` (bintu_api.mcp_streamable): the standard MCP Streamable HTTP
  endpoint (JSON-RPC 2.0, stateless) used by Claude connectors and Claude
  Code. Tool definitions are shared via TOOL_NAME/TOOL_TITLE/TOOL_DESCRIPTION/
  TOOL_INPUT_SCHEMA/TOOL_OUTPUT_SCHEMA/TOOL_ANNOTATIONS so both surfaces stay in lockstep.
"""


import asyncio
import json
import logging
from typing import Any


from fastapi import APIRouter, HTTPException, Request, Security
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


from bintu_api import routes
from bintu_api.auth import (
    api_key_scheme,
    mcp_rate_limit_identity,
    verify_mcp_api_access,
)
from bintu_api.context import _decode_source_text, extract_context, normalize_mode
from bintu_api.settings import Settings



router = APIRouter(prefix="/mcp", tags=["MCP"])


logger = logging.getLogger("bintu_api.mcp")
TOOL_NAME = "bintu_scrape_text"
TOOL_TITLE = "Bintu Scrape Text"
TOOL_DESCRIPTION = (
    "Token-Sanitized Context Gateway for AI agents: fetches one public "
    "absolute http(s) URL (1 MiB cap, HTML/XHTML only, nav/ads/footer stripped, "
    "article/main preferred) and returns readable text capped at 6,000 characters. "
    "Default mode=scrape returns the token-metered envelope. "
    "Use mode=chunk (alias chunked) to split text into max_tokens-sized chunks "
    "ready for vector databases; use mode=summarize to truncate to a token budget. "
    "Every call returns tokens, chunk_count, cache_hit, tokens_saved_estimate "
    "for predictable context budgets. "
    "truncated=true means content was actually lost (the 6,000-character cap, or "
    "summarize dropping sentences); split=true only means the text was divided "
    "across several chunks, which never loses anything. "
    "tokens is an approximate whitespace-token count (about one per word), not a "
    "real tokenizer, so treat it as a sizing estimate rather than an exact billing "
    "figure; tokens_saved_estimate is nonzero only in summarize mode. "
    "The 6,000-character cap binds before any token budget is enforced; if your "
    "application has a smaller token budget, set max_tokens accordingly. "
    "JavaScript rendering is disabled unless enabled — render_js_disabled means "
    "retry with render_js=false. "
    "Fails cleanly with invalid_or_unsafe_url, render_js_disabled, rate_limited — "
    "all in-band so the model can self-correct."
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
    "properties": {
        "content": {
            "type": "array",
            "description": (
                "MCP content blocks. content[0].text is always the unified JSON envelope: "
                "{mode, tokens, chunk_count, cache_hit, source_url, extracted_at, "
                "tokens_saved_estimate, truncated, chunks:[{index, text, tokens}]} "
                "for predictable context budgets in every mode."
            ),
            "items": {
                "type": "object",
                "properties": {"type": {"type": "string"}, "text": {"type": "string"}},
                "required": ["type", "text"],
            },
        },
        "isError": {
            "type": "boolean",
            "description": "True when extraction failed; content[0].text holds a code-prefixed hint (e.g. invalid_or_unsafe_url, render_js_disabled).",
        },
    },
    "required": ["content"],
    "additionalProperties": False,
}
TOOL_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "format": "uri",
            "description": "Absolute public HTTP or HTTPS URL to extract. Private IPs, non-http schemes, and unsafe targets fail with invalid_or_unsafe_url.",
            "examples": ["https://www.iana.org/domains/reserved"],
        },
        "render_js": {
            "type": "boolean",
            "default": False,
            "description": "Render the page in Chromium before extracting text. Usually disabled on free infra; when off the call fails with render_js_disabled — retry with false.",
        },
        "mode": {
            "type": "string",
            "enum": ["scrape", "chunk", "summarize"],
            "default": "scrape",
            "description": (
                "Extraction mode: scrape returns the metered envelope; chunk splits text into "
                "max_tokens-sized chunks for vector databases (pitch alias: chunked); "
                "summarize truncates to a token budget."
            ),
        },
        "max_tokens": {
            "type": "integer",
            "default": 6000,
            "minimum": 100,
            "maximum": 50000,
            "description": "Token budget for chunk/summarize modes (ignored in scrape mode). Pitch alias: chunk_token_budget. Note: extracted text is always capped at 6,000 characters first, so that cap usually binds before this budget on long pages.",
        },
        "cache": {
            "type": "boolean",
            "default": True,
            "description": "Use the in-memory + Supabase cache when available.",
        },
    },
    "required": ["url"],
    "additionalProperties": False,
}



class ToolCallRequest(BaseModel):
    name: str
    arguments: dict[str, Any]



class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


    url: str
    render_js: bool = False
    mode: str = "scrape"
    max_tokens: int = Field(default=6000, ge=100, le=50000)
    cache: bool = True


    @model_validator(mode="before")
    @classmethod
    def _normalize_aliases(cls, data: Any) -> Any:
        """Map pitch-name aliases to canonical values (case/whitespace tolerant).


        - mode "chunked" (any case/whitespace) -> "chunk".
        - "chunk_token_budget" -> "max_tokens"; canonical "max_tokens" wins
          on conflict with a warning. Range-checked after normalization.
        """
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        if "chunk_token_budget" in normalized:
            if "max_tokens" in normalized:
                logger.warning(
                    "mcp_alias_conflict canonical=max_tokens wins over chunk_token_budget"
                )
                normalized.pop("chunk_token_budget")
            else:
                normalized["max_tokens"] = normalized.pop("chunk_token_budget")
        max_tokens = normalized.get("max_tokens", 6000)
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int):
            raise ValueError("max_tokens must be an integer")
        return normalized



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
async def call_tool(payload: ToolCallRequest, request: Request) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    verify_mcp_api_access(request, settings)
    if payload.name != TOOL_NAME:
        raise HTTPException(status_code=400, detail=f"Unknown MCP tool: {payload.name}")
    # Strict mode validation before Pydantic: reject unknown modes with HTTP 400
    # so callers get a clean error instead of a 500 from extract_context.
    raw_mode = payload.arguments.get("mode")
    if raw_mode is not None:
        try:
            normalize_mode(raw_mode)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
    try:
        arguments = ToolArguments.model_validate(payload.arguments)
    except ValidationError as error:
        raise HTTPException(status_code=400, detail=error.errors()) from error


    if arguments.render_js and not settings.render_js_enabled:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "render_js_disabled",
                "message": "JavaScript rendering is disabled on this service.",
                "hint": "Retry with render_js=false for plain HTML extraction.",
            },
        )


    # Fetch and extract once through the shared REST pipeline boundary. This
    # keeps the legacy helper aligned with REST and the Streamable MCP endpoint
    # while allowing tests to patch bintu_api.routes.fetch_html_document.
    document = await asyncio.to_thread(
        routes.fetch_html_document, arguments.url, settings
    )
    extracted = routes.extract_text_result(
        document.body,
        settings.max_text_characters,
        include_nav=False,
        include_header=False,
        include_footer=False,
        from_encoding=document.charset,
        base_url=document.final_url or arguments.url,
    )


    context = await extract_context(
        request,
        arguments.url,
        mode=arguments.mode,
        max_tokens=arguments.max_tokens,
        cache=arguments.cache,
        render_js=arguments.render_js,
        identity=mcp_rate_limit_identity(request, settings),
        raw_text=extracted.text,
        content_truncated=extracted.truncated,
        html_source_text=_decode_source_text(document),
        cache_hit=False,
        cache_layer="none",
        document=document,
        settings=settings,
    )


    # Unified Token Tax envelope in content[0].text across ALL modes.
    # `tokens` is a deprecated alias of `approx_tokens` (kept for one release);
    # `token_method` names the counter; `html_tokens` is the fetched-document
    # baseline for `tokens_saved_estimate`; `limiting_factor` says which cap bound.
    payload = {
        "mode": context.mode,
        "tokens": context.tokens,
        "approx_tokens": context.approx_tokens,
        "html_tokens": context.html_tokens,
        "token_method": context.token_method,
        "limiting_factor": context.limiting_factor,
        "chunk_count": context.chunk_count,
        "cache_hit": context.cache_hit,
        "source_url": context.source_url,
        "extracted_at": context.extracted_at,
        "tokens_saved_estimate": context.tokens_saved_estimate,
        "truncated": context.truncated,
        "split": context.split,
        "chunks": context.chunks,
    }
    return {
        "content": [{"type": "text", "text": json.dumps(payload)}],
        "isError": False,
    }