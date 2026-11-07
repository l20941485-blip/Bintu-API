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
    "Fetch one public HTTP or HTTPS URL and return its readable text, sized for an LLM context window. "
    "Only HTML/XHTML pages up to 1 MiB are supported (PDF, JSON, images and pages that need JavaScript are not). "
    "Article or main content is preferred; navigation, headers, footers, ads and cookie banners are dropped, "
    "repeated story blocks are removed (deduplicated_count), links appear as 'label (url)', code is returned "
    "in fenced blocks with indentation kept, and tables are pipe-delimited. "
    "Modes: scrape (default) returns the text trimmed to max_tokens; chunk splits it into chunks that each fit "
    "max_tokens (headings stay with their text, table header rows repeat in continuation chunks, and one "
    "indivisible unit such as a very long table row can exceed the budget); summarize returns the leading lines "
    "and whole sentences that fit max_tokens (it is not an AI-written summary). "
    "Pages are read up to about 200,000 characters (roughly 50,000 tokens): truncated=true with "
    "limiting_factor=char_cap means that ceiling was hit, token_budget means max_tokens was. "
    "tokens and approx_tokens are approximate estimates (characters divided by 4), not tokenizer counts; "
    "tokens_saved_estimate is the source-HTML estimate minus the tokens delivered in this response. "
    "low_yield=true means a large page produced very little text, usually because it needs JavaScript or a "
    "login; see yield_hint. "
    "Results may come from a cache (cache_hit, cache_layer): set cache=false to bypass cache reads and "
    "persist=false to skip the persistent write; URLs with credential-like query parameters are never stored. "
    "robots.txt is honored. JavaScript rendering (render_js) works only if the operator enables it. "
    "Failures return isError=true with a code such as invalid_or_unsafe_url, upstream_access_denied, "
    "blocked_by_robots, payload_too_large or unsupported_media_type."
)

URL_DESCRIPTION = (
    "Absolute public HTTP or HTTPS URL to read. Private, loopback, link-local and metadata addresses, "
    "non-standard ports and URLs containing credentials are rejected with invalid_or_unsafe_url."
)

MODE_DESCRIPTION = (
    "scrape: the page text trimmed to max_tokens. chunk: the whole page split into chunks that each fit "
    "max_tokens. summarize: the leading lines and whole sentences that fit max_tokens. "
    "'chunked' is accepted as an alias for chunk."
)

"For scrape mode, optional sections selects matching Markdown headings and returns their clipped bodies in selected_sections."

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
    "footnotes uses numbered references and a link list; false removes URLs for the lowest-token output."
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

SECTIONS_DESCRIPTION = (
    "Optional heading selectors for scrape mode. Accepts either a "
    "newline-separated string (for example \"Alpha\\nBeta\") or an array "
    "of strings (for example [\"Alpha\", \"Beta\"]). Whitespace and case "
    "are normalized for exact heading matching. Empty or whitespace-only "
    "selectors return invalid_arguments. Each selector must be 200 "
    "characters or fewer. When provided, the persistent and memory caches "
    "are bypassed for reads; a fresh extraction may still be written when "
    "persist is true."
)

OUTPUT_SCHEMA_EXTRA_PROPERTIES = {
    "deduplicated_count": {
        "type": "integer",
        "minimum": 0,
        "description": "Repeated story blocks removed from the extracted text.",
    },
    "low_yield": {
        "type": "boolean",
        "description": "True when a large page produced very little text (often JavaScript-rendered or login-gated).",
    },
    "yield_hint": {
        "type": "string",
        "description": "Present only when low_yield is true: a short suggestion for what to try next.",
    },
}
