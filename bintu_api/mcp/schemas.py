"""Tool metadata and JSON schema definitions for Bintu MCP.

This module owns the public tool contract and keeps JSON schema metadata separate from invocation logic and FastAPI routing.

Important boundaries, invariants, and compatibility notes are documented here so the module stays focused on its owned behavior without drifting into unrelated routing or storage concerns.
"""

from bintu_api.mcp.descriptions import (
    CACHE_DESCRIPTION,
    CHUNK_TOKEN_BUDGET_DESCRIPTION,
    FOOTNOTE_URL_POLICY_DESCRIPTION,
    LINKS_DESCRIPTION,
    MAX_FOOTNOTE_URL_LENGTH_DESCRIPTION,
    MAX_TOKENS_DESCRIPTION,
    MODE_DESCRIPTION,
    OUTPUT_SCHEMA_EXTRA_PROPERTIES,
    PERSIST_DESCRIPTION,
    RENDER_JS_DESCRIPTION,
    SECTIONS_DESCRIPTION,
    URL_DESCRIPTION,
)
from bintu_api.mcp.descriptions import TOOL_DESCRIPTION as TOOL_DESCRIPTION

TOOL_NAME = "bintu_scrape_text"
TOOL_TITLE = "Bintu Scrape Text"

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
            "description": "Extraction mode: scrape returns readable text; chunk splits it into budgeted chunks; summarize selects leading text within a budget. The accepted chunked alias normalizes to chunk.",
        },
        "tokens": {
            "type": "integer",
            "minimum": 0,
            "description": "Compatibility alias of approx_tokens.",
        },
        "approx_tokens": {
            "type": "integer",
            "minimum": 0,
            "description": "Approximate token count of the returned text: ceil(characters / 4). An estimate, not a tokenizer count.",
        },
        "html_tokens": {
            "type": "integer",
            "minimum": 0,
            "description": "Approximate token count of the fetched source HTML, computed the same way as approx_tokens.",
        },
        "token_method": {
            "type": "string",
            "description": "Method used to compute approx_tokens: ceil(characters / 4).",
        },
        "limiting_factor": {
            "type": "string",
            "description": "Which limit bound the returned text: char_cap (extracted-text character ceiling) or token_budget (max_tokens), or none when no limit shortened the response.",
        },
        "chunk_count": {
            "type": "integer",
            "minimum": 0,
            "description": "Number of chunks in the chunks array (1 for scrape and summarize modes when not split).",
        },
        "cache_hit": {
            "type": "boolean",
            "description": "True when the response was served from memory or persistent cache.",
        },
        "cache_layer": {
            "type": "string",
            "description": "Which cache served the response: none, memory, or persistent.",
        },
        "source_url": {
            "type": "string",
            "description": "The requested URL with sensitive-looking query parameters removed, safe for logs and display.",
        },
        "extracted_at": {
            "type": "string",
            "description": "UTC ISO 8601 timestamp of the extraction.",
        },
        "tokens_saved_estimate": {
            "type": "integer",
            "minimum": 0,
            "description": "Estimated tokens saved by extraction: source-HTML approximate tokens minus returned-text approximate tokens, floored at 0.",
        },
        "truncated": {
            "type": "boolean",
            "description": "True when extracted content exceeded a limit and the returned text was shortened.",
        },
        "split": {
            "type": "boolean",
            "description": "True when content spans multiple chunks (chunk mode only; not truncation).",
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
                "Approximate token budget, enforced in every mode: scrape "
                "trims to it, chunk makes each chunk fit it, summarize returns "
                "the leading text within it. Range 100 to 50000, default 6000. "
                "Accepted alias: chunk_token_budget. A single indivisible unit "
                "in chunk mode, and a first oversized sentence in summarize "
                "mode, may exceed the budget."
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
TOOL_INPUT_SCHEMA["properties"]["chunk_token_budget"]["description"] = CHUNK_TOKEN_BUDGET_DESCRIPTION
TOOL_INPUT_SCHEMA["properties"]["cache"]["description"] = CACHE_DESCRIPTION
TOOL_INPUT_SCHEMA["properties"]["persist"]["description"] = PERSIST_DESCRIPTION
TOOL_INPUT_SCHEMA["properties"]["render_js"]["description"] = RENDER_JS_DESCRIPTION
TOOL_INPUT_SCHEMA["properties"]["links"]["description"] = LINKS_DESCRIPTION
TOOL_INPUT_SCHEMA["properties"]["footnote_url_policy"]["description"] = FOOTNOTE_URL_POLICY_DESCRIPTION
TOOL_INPUT_SCHEMA["properties"]["sections"] = {
    "oneOf": [
        {
            "type": "string",
            "description": SECTIONS_DESCRIPTION,
        },
        {
            "type": "array",
            "items": {"type": "string"},
            "description": SECTIONS_DESCRIPTION,
        },
    ],
    "description": SECTIONS_DESCRIPTION,
}
TOOL_INPUT_SCHEMA["properties"]["max_footnote_url_length"]["description"] = MAX_FOOTNOTE_URL_LENGTH_DESCRIPTION
TOOL_OUTPUT_SCHEMA["properties"].update(OUTPUT_SCHEMA_EXTRA_PROPERTIES)



