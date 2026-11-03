# API reference

This reference describes the deployed Bintu REST and MCP interfaces. For
interactive testing, use `/docs`; the live OpenAPI document is at
`/openapi.json`.

## Base URL and authentication

```text
https://bintu-api.onrender.com
```

| Surface | Authentication |
|---|---|
| REST scrape and metrics | Master `API_KEY` in `X-API-Key`, or configured RapidAPI proxy authentication |
| MCP discovery | No credential for `initialize`, `tools/list`, and `ping` |
| MCP tool execution | Scoped `MCP_API_KEY` or master `API_KEY` in `X-API-Key` or `Authorization: Bearer` |
| Mobile scrape | Supabase user access token in `Authorization: Bearer`; verified email required |
| Reader | Master `API_KEY` in `X-API-Key`, or a verified RapidAPI subscriber identity |

An MCP-scoped key does not grant REST access. Never put credentials in a URL
or source code.

## REST endpoints

### `GET /`

Returns service status and the relative path to API documentation.

### `GET /healthz`

Unauthenticated health and deployment metadata, including `status`, `version`,
and, when supplied by Render, `commit` and `environment`.

### `GET /version`

Returns non-secret service configuration, including version, fetch limits,
rate limits, and cache TTL.

### `GET /metrics`

Returns Prometheus metrics. Requires the same service authentication as REST.

### `GET /api/v1/scrape/text`

Extracts readable text from a public HTML or XHTML page.

| Query parameter | Type | Default | Description |
|---|---|---:|---|
| `url` | string | required | Absolute public HTTP(S) URL |
| `max_tokens` | integer | 6000 | Approximate response budget; 100–50,000 |
| `include_nav` | boolean | false | Preserve navigation elements |
| `include_header` | boolean | false | Preserve header elements |
| `include_footer` | boolean | false | Preserve footer elements |
| `render_js` | boolean | false | Request browser rendering; disabled unless enabled by the operator |
| `links` | string | `inline` | `inline`, `footnotes`, or `false` |
| `footnote_url_policy` | string | `truncated` | `truncated` caps over-limit footnote destinations as non-clickable text; `full` preserves complete destinations. Applies only when `links=footnotes` |
| `max_footnote_url_length` | integer | 100 | Positive maximum URL length for footnote labels and, with the `truncated` policy, destinations. Applies only when `links=footnotes` |
| `skip_cache` | boolean | false | Bypass cache reads |
| `persist` | boolean | true | Allow a fresh successful result to be written to persistent cache |

Footnotes deduplicate equivalent destinations and cap their visible labels at
`max_footnote_url_length`. The default `footnote_url_policy=truncated`
replaces over-limit destinations with a safe, non-clickable abbreviated
display, marked `[URL truncated]`. Set `footnote_url_policy=full` to retain
complete destinations. Both options are ignored for other `links` modes.

The response includes the requested URL, extracted `text`, `truncated`,
`limiting_factor`, approximate token counts, cache metadata, low-yield
information, and optional provenance. `approx_tokens` is estimated as
`ceil(characters / 4)`, not with a model tokenizer.

### `POST /api/v1/scrape/chunks`

Uses the same fetch, authentication, robots, cache, and extraction pipeline,
then returns ordered text chunks. The JSON body accepts `url`,
`include_nav`, `include_header`, `include_footer`, and `render_js`.
The `max_tokens` query parameter defaults to 6000 and accepts 100–50,000;
it budgets each chunk. The decoded upstream HTML limit is 1 MiB, and the
extracted-text ceiling is 200,000 characters.

### `POST /api/v1/mobile/scrape/text`

Accepts a JSON body containing `url` and optional inclusion flags. Requires a
valid Supabase user bearer token and verified email. Returns the standard
scrape response.

### `POST /api/v1/reader/read` and `POST /api/v1/reader/continue`

The reader fetches one page into a bounded text snapshot and returns pages
using an opaque continuation cursor. Both endpoints require reader
authentication. The initial request accepts `url`, `max_tokens` (1–6000,
default 1000), and inclusion flags. Continuation accepts `cursor` and
`max_tokens`. Snapshots are process-local, expire after 600 seconds, and may
be evicted sooner; they are not shared across workers or instances.

## MCP

### Stateless Streamable HTTP: `POST /mcp`

Send one JSON-RPC 2.0 message per `application/json` POST. The server returns a
single JSON response; it does not create resumable sessions or push SSE
messages.

These methods are public discovery/liveness operations:

- `initialize`
- `tools/list`
- `ping`

`tools/call` requires the scoped `MCP_API_KEY` or master `API_KEY`.
The advertised tool is `bintu_scrape_text`. Successful calls return the
extraction envelope in `structuredContent` and as JSON in
`content[0].text`. Tool execution errors are returned in-band with
`isError: true`.

`GET /mcp` returns an immediately closing, empty `text/event-stream`
response. `GET /sse` and `GET /mcp/sse` are compatibility aliases.

The MCP request body is limited to 64 KiB by the application. A deployment
behind a trusted CDN, reverse proxy, or API gateway should enforce the same
limit there as well.

### Legacy MCP helpers

`GET /mcp/tools` advertises the tool schema. `POST /mcp/tools/call` invokes
the tool and requires MCP authentication.

### Tool inputs and budgets

`url` is required. Optional inputs include `mode` (`scrape`, `chunk`, or
`summarize`; `chunked` is an alias), `max_tokens` (default 6000, range
100–50,000), `links`, `footnote_url_policy` (`full` or `truncated`, default
`truncated`), `max_footnote_url_length` (positive integer, default 100),
`render_js`, `cache`, and `persist`. The footnote URL options apply only when
`links=footnotes`; truncated destinations are non-clickable abbreviated text.
Token counts are approximate. `summarize` selects leading text; it is not
an AI-generated summary.

## Error behavior

REST errors use a JSON `detail` object with a stable `code` and `message`.
MCP tool execution failures use the corresponding code in the in-band error
text.

| Condition | REST result | MCP tool error code |
|---|---|---|
| Invalid or unsafe target URL | HTTP 400, `invalid_or_unsafe_url` | `invalid_or_unsafe_url` |
| Robots disallow or robots unavailable | HTTP 403, `blocked_by_robots` or `robots_unreachable` | Same code |
| Caller burst limit | HTTP 429, `burst_rate_limit_exceeded` | Same code |
| Upstream returns HTTP 429 | HTTP 502, `upstream_rate_limited` | `upstream_rate_limited` |
| Upstream returns HTTP 401, 402, or 403 | HTTP 502, `upstream_access_denied` | `upstream_access_denied` |
| Other upstream HTTP error | HTTP 502, `upstream_http_error` | `upstream_http_error` |
| Upstream body exceeds 1 MiB | HTTP 413, `payload_too_large` | `payload_too_large` |
| Unsupported response media type | HTTP 415, `unsupported_media_type` | `unsupported_media_type` |
| Request body exceeds MCP limit | HTTP 413, JSON-RPC `-32600` | Not applicable |

## Service limits

| Limit | Value |
|---|---:|
| Decoded upstream HTML | 1 MiB |
| Redirects | 5 |
| Default scrape/MCP token budget | 6000 |
| Scrape/MCP token budget range | 100–50,000 |
| Extracted-text ceiling for chunk/MCP modes | 200,000 characters |
| MCP JSON-RPC request body | 64 KiB |
| Default burst limit | 60 requests per 60 seconds |
| Default process-local cache TTL | 300 seconds |
| JavaScript rendering | Disabled unless enabled by the operator |

`X-Request-ID` is returned for request correlation. Share it when reporting
an issue; do not share API keys, bearer tokens, continuation cursors, or
private page content.
