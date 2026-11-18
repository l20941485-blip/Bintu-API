"""Accurate text for the MCP tool definition (bintu_api/mcp.py).

This module owns the canonical human-readable description text used in the
MCP tool surface. All strings here describe live, verified behavior:

- Pages are read up to about 200,000 characters (roughly 50,000 tokens).
- max_tokens is enforced in every mode (scrape trims, chunk budgets, summarize truncates).
- Chunk mode preserves headings with their text, repeats table header rows in continuation chunks, and allows one indivisible unit to exceed the budget.
- Summarize returns leading lines and whole sentences; it is not an AI-written summary.
- Tokens are approximate estimates (ceil(characters / 4)), not tokenizer counts.
- Cache behavior, low-yield handling, and error semantics match the live service.

Integration (mcp/schemas.py): import TOOL_DESCRIPTION and the per-parameter
description constants below, and merge OUTPUT_SCHEMA_EXTRA_PROPERTIES into
TOOL_OUTPUT_SCHEMA["properties"] (they are NOT added to "required").
"""

TOOL_DESCRIPTION = (
    "Fetch one public HTTP or HTTPS URL and return readable text sized for an LLM "
    "context window. Supports scrape, chunk, and summarize modes; scrape returns "
    "text trimmed to max_tokens, chunk splits the page into chunks that each fit "
    "max_tokens, and summarize returns leading lines and whole sentences within "
    "max_tokens (not an AI-written summary). Pages are read up to 200,000 "
    "characters; truncated=true with limiting_factor=char_cap means that ceiling "
    "was hit, while token_budget means max_tokens was. Token counts are approximate "
    "estimates, not tokenizer counts; tokens_saved_estimate reports estimated "
    "savings. low_yield=true includes yield_hint. Results may come from cache "
    "(cache_hit, cache_layer); set cache=false to bypass cache reads and "
    "persist=false to skip the persistent write. URLs with credential-like query "
    "parameters are never stored, and robots.txt is honored. render_js requires "
    "operator enablement. Failures return isError=true with stable codes such as "
    "invalid_or_unsafe_url, upstream_access_denied, blocked_by_robots, "
    "payload_too_large, unsupported_media_type, upstream_rate_limited, and "
    "upstream_http_error. Repeated story blocks are excluded (deduplicated_count); "
    "code is returned in fenced blocks; tables are pipe-delimited."
)

URL_DESCRIPTION = (
    "Absolute public HTTP or HTTPS URL to read. Private, loopback, link-local and metadata addresses, "
    "non-standard ports and URLs containing credentials are rejected with invalid_or_unsafe_url."
)

MODE_DESCRIPTION = (
    "scrape: selected page text trimmed to max_tokens. chunk: selected page text "
    "split into chunks that each fit max_tokens. summarize: leading lines and whole "
    "sentences from selected page text within max_tokens. When sections is provided, "
    "it filters the page before mode processing; if no section matches, no page "
    "content is returned. 'chunked' is accepted as an alias for chunk."
)

MAX_TOKENS_DESCRIPTION = (
    "Estimated-token budget, enforced in every mode: scrape trims to it, chunk makes each chunk fit it, "
    "summarize returns the leading text within it. Range 100 to 50000, default 6000. "
    "A single indivisible unit in chunk mode (for example one very long table row) can exceed it. "
    "Accepted alias: chunk_token_budget."
)

CACHE_DESCRIPTION = (
    "Read from the memory and persistent caches (default true). false bypasses cache reads; "
    "a fresh result may still be written to the cache."
)

PERSIST_DESCRIPTION = (
    "Allow a fresh result to be written to the persistent cache (default true). false skips that write; "
    "extraction and the short-lived memory cache are unchanged."
)

RENDER_JS_DESCRIPTION = (
    "Render the page in a browser before extraction. Available only if the operator enables it; "
    "otherwise render_js_disabled is returned and you should retry with false."
)

LINKS_DESCRIPTION = (
    "How to represent hyperlinks in extracted text. inline preserves readable link URLs; "
    "footnotes uses numbered references and a link list; false omits URLs for the lowest-token output."
)

FOOTNOTE_URL_POLICY_DESCRIPTION = (
    "For links=footnotes only: full preserves complete URL destinations; truncated replaces "
    "over-limit destinations with non-clickable abbreviated text. Default: truncated."
)

MAX_FOOTNOTE_URL_LENGTH_DESCRIPTION = (
    "For links=footnotes only: maximum URL length for the visible label and, with the "
    "truncated policy, the destination. Positive integer. Default: 100."
)

CHUNK_TOKEN_BUDGET_DESCRIPTION = (
    "Accepted alias for max_tokens; max_tokens wins on conflict. Range 100 to 50000."
)

MAIN_CONTENT_ONLY_DESCRIPTION = (
    "Apply stronger main-content extraction before sections filtering and "
    "mode processing. When true, Bintu prefers the primary article or "
    "documentation container and reduces navigation, sidebars, footers, and "
    "non-article boilerplate before scrape, chunk, summarize, and sections "
    "processing. Default false preserves current extraction behavior. "
    "Cleaned requests use memory caching only."
)

CONTENT_CLEANING_DESCRIPTION = (
    "Reports whether stronger main-content extraction was applied to the "
    "source page. strategy is main_content when cleaning succeeded and "
    "standard when Bintu used its regular extraction path."
)

SECTIONS_DESCRIPTION = (
    "Optional heading selectors that filter the page before mode processing. "
    "Accepts either a newline-separated string (for example \"Alpha\\nBeta\") or "
    "an array of strings (for example [\"Alpha\", \"Beta\"]). Whitespace and case "
    "are normalized for heading matching. When provided, scrape returns only "
    "matching sections, chunk/chunked splits only matching sections, and "
    "summarize summarizes only matching sections. If no requested section "
    "matches, the response contains no page content and reports no_match. "
    "Empty or whitespace-only selectors return invalid_arguments. Each selector "
    "must be 200 characters or fewer. When provided, persistent and memory "
    "caches are bypassed for reads; a fresh extraction may still be written "
    "when persist is true."
)

OUTPUT_SCHEMA_EXTRA_PROPERTIES = {
    "page_title": {
        "type": "string",
        "description": (
            "Human-readable title of the source document, when available."
        ),
    },
    "page_title_source": {
        "type": "string",
        "enum": ["html_title", "heading", "url_fallback", "none"],
        "description": (
            "Origin of page_title: html_title, heading, url_fallback, "
            "or none."
        ),
    },
    "deduplicated_count": {
        "type": "integer",
        "minimum": 0,
        "description": "Repeated story blocks excluded from the extracted text.",
    },
    "low_yield": {
        "type": "boolean",
        "description": "True when a large page produced very little text (often JavaScript-rendered or login-gated).",
    },
    "yield_hint": {
        "type": "string",
        "description": "Present only when low_yield is true: a short suggestion for what to try next.",
    },
    "requested_sections": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Section selectors requested by the caller.",
    },
    "unmatched_sections": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Requested section selectors that did not match a heading or label.",
    },
    "available_sections": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Headings and labels available in the extracted document.",
    },
    "filtered": {
        "type": "boolean",
        "description": "True when a sections filter was applied before mode processing.",
    },
    "section_match_status": {
        "type": "string",
        "enum": ["not_filtered", "matched", "partial_match", "no_match"],
        "description": "Outcome of section selection.",
    },
    "warnings": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Non-fatal section-selection warnings.",
    },
}
