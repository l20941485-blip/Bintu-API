"""Tool metadata and JSON schema definitions for Bintu MCP.

This module owns the public tool contract and keeps JSON schema metadata separate from invocation logic and FastAPI routing.

Important boundaries, invariants, and compatibility notes are documented here so the module stays focused on its owned behavior without drifting into unrelated routing or storage concerns.
"""

from bintu_api.mcp_descriptions import (
    CACHE_DESCRIPTION,
    MAX_TOKENS_DESCRIPTION,
    MODE_DESCRIPTION,
    OUTPUT_SCHEMA_EXTRA_PROPERTIES,
    PERSIST_DESCRIPTION,
    RENDER_JS_DESCRIPTION,
    TOOL_DESCRIPTION,
    URL_DESCRIPTION,
)

TOOL_NAME = "bintu_scrape_text"
TOOL_TITLE = "Bintu Scrape Text"
TOOL_DESCRIPTION = TOOL_DESCRIPTION

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
