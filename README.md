# Bintu Data Extraction API

## Quickstart

### 1. Authenticate

Send your service key in the `X-API-Key` header. Do not put API keys in URLs.

```powershell
$BaseUrl = "https://your-bintu-api.onrender.com"
$ApiKey  = $env:BINTU_API_KEY
```

### 2. Extract readable text

```powershell
$url = "https://example.com"

$response = Invoke-RestMethod `
  -Method Get `
  -Uri "$BaseUrl/api/v1/scrape/text?url=$([uri]::EscapeDataString($url))" `
  -Headers @{ "X-API-Key" = $ApiKey }

$response.text
$response.approx_tokens
$response.truncated
```

The response includes `text`, an approximate token count, and `truncated`. If a page returns very little readable text, the response may include `low_yield: true` and a short `yield_hint`, such as a note that the page appears to require JavaScript.

### 3. Use MCP

MCP discovery (`initialize`, `tools/list`, `ping`) is available without a key.
Tool execution requires either the scoped `MCP_API_KEY` or the master `API_KEY`,
sent as `X-API-Key` or `Authorization: Bearer`.

```powershell
$body = @{
  jsonrpc = "2.0"
  id = 1
  method = "tools/call"
  params = @{
    name = "bintu_scrape_text"
    arguments = @{
      url = "https://example.com"
      max_tokens = 2000
    }
  }
} | ConvertTo-Json -Depth 10

Invoke-RestMethod `
  -Method Post `
  -Uri "$BaseUrl/mcp" `
  -Headers @{
    "X-API-Key" = $ApiKey
    "Accept" = "application/json, text/event-stream"
  } `
  -ContentType "application/json" `
  -Body $body
```

#### What `bintu_scrape_text` does

Fetches one public HTTP or HTTPS URL and returns its readable text, sized for an LLM context window. Only HTML/XHTML pages up to 1 MiB are supported; PDF, JSON, images, and pages that require JavaScript are not. Article or main content is preferred; navigation, headers, footers, ads, and cookie banners are dropped; repeated story blocks are removed (`deduplicated_count`); links appear as `label (url)`; code is returned in fenced blocks with indentation kept; tables are pipe-delimited.

#### When to use it

- You need readable, token-bounded text from a public web page for an LLM context window.
- You want chunks sized for a vector database (`mode=chunk`).
- You want a short leading extract within a budget (`mode=summarize`).
- You want cache-aware extraction with provenance and token economics.

#### Input parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `url` | string | required | Absolute public HTTP(S) URL. Private, loopback, link-local, and metadata addresses, non-standard ports, and URLs containing credentials are rejected with `invalid_or_unsafe_url`. |
| `mode` | string | `scrape` | `scrape` returns readable text trimmed to `max_tokens`; `chunk` splits the page into budgeted chunks; `summarize` returns leading text within `max_tokens`. `chunked` is accepted as an alias for `chunk`. |
| `max_tokens` | integer | 6000 | Approximate token budget, enforced in every mode (range 100–50,000). Accepted alias: `chunk_token_budget`. |
| `chunk_token_budget` | integer | — | Accepted alias for `max_tokens`; `max_tokens` wins on conflict. |
| `links` | string | `inline` | `inline` preserves readable link URLs; `footnotes` uses numbered references and a link list; `false` removes URLs for the lowest-token output. |
| `footnote_url_policy` | string | `truncated` | For `links=footnotes` only: `full` preserves complete destinations; `truncated` replaces over-limit destinations with non-clickable text. |
| `max_footnote_url_length` | integer | 100 | For `links=footnotes` only: maximum URL length for visible labels and truncated destinations. |
| `render_js` | boolean | false | Render in a browser before extraction. Available only if the operator enables it; otherwise `render_js_disabled` is returned. |
| `cache` | boolean | true | Read from memory and persistent caches. `false` bypasses cache reads. |
| `persist` | boolean | true | Allow a fresh successful result to be written to the persistent cache. `false` skips that write.

#### Output envelope

Every successful call returns the same JSON envelope (in `structuredContent` and as JSON in `content[0].text`):

| Field | Type | Description |
|---|---|---|
| `mode` | string | Extraction mode used (`scrape`, `chunk`, or `summarize`). |
| `tokens` | integer | Compatibility alias of `approx_tokens`. |
| `approx_tokens` | integer | Approximate token count of the returned text (`ceil(characters / 4)`). |
| `html_tokens` | integer | Approximate token count of the fetched source HTML. |
| `token_method` | string | Method used to compute `approx_tokens`: `ceil(characters / 4)`. |
| `limiting_factor` | string | `char_cap`, `token_budget`, or `none` — which limit bound the response. |
| `chunk_count` | integer | Number of chunks in `chunks`. |
| `cache_hit` | boolean | True when served from memory or persistent cache. |
| `cache_layer` | string | `none`, `memory`, or `persistent`. |
| `source_url` | string | Requested URL with sensitive-looking query parameters removed. |
| `extracted_at` | string | UTC ISO 8601 timestamp of the extraction. |
| `tokens_saved_estimate` | integer | Source-HTML estimate minus returned-text estimate, floored at 0. |
| `truncated` | boolean | True when content exceeded a limit and text was shortened. |
| `split` | boolean | True when content spans multiple chunks (chunk mode only). |
| `chunks` | array | Each item: `{index, text, tokens, approx_tokens}`. |
| `deduplicated_count` | integer | Repeated story blocks removed. |
| `low_yield` | boolean | True when a large page produced very little text. |
| `yield_hint` | string | Present only when `low_yield` is true. |
| Provenance fields* | — | `request_id`, `fetched_at`, `requested_url`, `final_url`, `content_type`, `bytes_fetched`, `content_sha256`, `cache`, `extractor_version` — present when available. |

\* Provenance fields are additive and may be absent.

#### Error semantics

Tool execution failures are returned in-band with `isError: true` and a stable error object at `structuredContent.error` (`code`, `message`, optional `hint`, optional `retryable`, optional `retry_with`), with the same code and message in `content[0].text`.

| Condition | MCP error code | Retryable? |
|---|---|---|
| Invalid or unsafe URL | `invalid_or_unsafe_url` | No |
| Robots disallow | `blocked_by_robots` | No |
| Robots unavailable | `robots_unreachable` | No |
| Caller burst limit | `burst_rate_limit_exceeded` | Yes (after `Retry-After`) |
| Upstream HTTP 429 | `upstream_rate_limited` | Yes (`retry_after_delay`) |
| Upstream HTTP 401/402/403 | `upstream_access_denied` | No |
| Other upstream HTTP error | `upstream_http_error` | No |
| Body exceeds 1 MiB | `payload_too_large` | No |
| Unsupported media type | `unsupported_media_type` | No |
| Unsupported encoding | `unsupported_content_encoding` | No |
| Too many redirects | `too_many_redirects` | No |
| Timeout or connection failure | `upstream_timeout` / `upstream_connection_error` | No |
| JavaScript disabled | `render_js_disabled` | No (retry with `render_js=false`) |
| JavaScript render failure | `upstream_render_error` | No |
| Invalid tool arguments | `invalid_arguments` | No |

#### Retry behavior

Only `upstream_rate_limited` is retryable (`retryable=true`, `retry_with="retry_after_delay"`). Wait for the indicated delay before retrying. All other errors are non-retryable; do not retry them unchanged.

#### Cache behavior

Results may be served from memory or persistent cache (`cache_hit`, `cache_layer`). Set `cache=false` to bypass cache reads; set `persist=false` to skip the persistent write. URLs with credential-like query parameters are never stored. `robots.txt` is honored.

#### Token economics

`approx_tokens` is `ceil(characters / 4)`, an estimate, not a tokenizer count. `tokens_saved_estimate` is the source-HTML estimate minus the returned-text estimate. `html_tokens` reports the source size the same way. Use these fields to budget LLM context before and after extraction.

#### Rate limits

The service applies a per-process burst limit (60 requests per 60 seconds by default). A burst-limit response (`429 burst_rate_limit_exceeded` on REST; `upstream_rate_limited` on MCP) includes a `Retry-After` hint. Pause and retry after that delay; do not retry immediately.

### Common responses

| Situation | What to check |
|---|---|
| `401 invalid_api_key` | Send a valid REST `X-API-Key`; an MCP-only key does not unlock REST routes. |
| `truncated: true` | Raise `max_tokens`, or request the next chunk using the continuation endpoint. |
| `low_yield: true` | Try a print, AMP, RSS, or server-rendered version of the page. |

Bintu is a FastAPI-based API for extracting readable text from public HTML pages. It limits upstream responses to 1 MiB, accepts HTML/XHTML only, pins outbound connections to validated public IPs, and applies a 60-request per-minute process-local burst limit.

## Live API

The service is live on Render and ready to test:

- Base URL: https://bintu-api.onrender.com
- OpenAPI docs: https://bintu-api.onrender.com/docs
- Health check: https://bintu-api.onrender.com/healthz

### Health check

```bash
curl https://bintu-api.onrender.com/healthz
```

Example response:

```json
{
  "status": "ok"
}
```

### Scrape text

For direct access to the deployed service, set your API key in PowerShell. The secure prompt avoids echoing the key as you type:

```powershell
$env:BINTU_BASE_URL = "https://bintu-api.onrender.com"
$secure = Read-Host "Paste your Render API_KEY" -AsSecureString
$env:BINTU_API_KEY = [System.Net.NetworkCredential]::new("", $secure).Password
Remove-Variable secure
```

Send an authenticated scrape request:

```powershell
$target = "https://www.iana.org/domains/reserved"
$encodedUrl = [uri]::EscapeDataString($target)
$headers = @{ "X-API-Key" = $env:BINTU_API_KEY }

try {
    $result = Invoke-RestMethod `
        -Uri "$env:BINTU_BASE_URL/api/v1/scrape/text?url=$encodedUrl" `
        -Headers $headers
    $result | ConvertTo-Json -Depth 5
}
catch {
    $response = $_.Exception.Response
    if ($response) {
        $statusCode = [int]$response.StatusCode
        $retryAfter = $response.Headers["Retry-After"]
        Write-Host "HTTP $statusCode; Retry-After: $retryAfter"
        $reader = [System.IO.StreamReader]::new($response.GetResponseStream())
        try { $reader.ReadToEnd() } finally { $reader.Dispose() }
    }
    else {
        throw
    }
}
```

Successful response:

```json
{
  "url": "https://www.iana.org/domains/reserved",
  "text": "# IANA-managed Reserved Domains\n## Example domains\n...",
  "truncated": false
}
```

`truncated` is `true` if the extracted text exceeded the configured character limit. The API returns the requested URL in `url`.

For `curl.exe` in PowerShell, the same request can be made with:

```powershell
curl.exe --get "$env:BINTU_BASE_URL/api/v1/scrape/text" `
  --data-urlencode "url=https://www.iana.org/domains/reserved" `
  --header "X-API-Key: $env:BINTU_API_KEY" `
  --header "Accept: application/json"
```

The Render `API_KEY` is available in the service's Environment settings. Keep it private, do not commit it, and do not put it in a URL. The examples above keep it in the current PowerShell process environment. If no API key or proxy secret is configured (as in the default local development setup), authentication is not required. Interactive API docs are available at [`/docs`](https://bintu-api.onrender.com/docs) — click **Authorize** (top right) and paste the key into `ApiKeyAuth`, or the Supabase session token into `BearerAuth` for the mobile endpoint, then use **Try it out** on any locked route.

### Scrape chunks

Use `POST /api/v1/scrape/chunks` when the extracted page needs to be divided into model-friendly, approximately token-budgeted pieces. This is useful for long articles, documentation, and retrieval workflows.

Set the API key as shown in [Scrape text](#scrape-text), then send:

```powershell
$target = "https://www.iana.org/domains/reserved"

$body = @{
    url = $target
    include_nav = $false
    include_header = $false
    include_footer = $false
    render_js = $false
} | ConvertTo-Json

$result = Invoke-RestMethod `
    -Method Post `
    -Uri "$env:BINTU_BASE_URL/api/v1/scrape/chunks?max_tokens=1000" `
    -Headers @{ "X-API-Key" = $env:BINTU_API_KEY } `
    -ContentType "application/json" `
    -Body $body

$result | ConvertTo-Json -Depth 5
```

The response contains ordered chunks:

```json
{
  "url": "https://www.iana.org/domains/reserved",
  "mode": "chunk",
  "max_tokens": 1000,
  "split": true,
  "chunk_count": 3,
  "chunks": [
    {
      "index": 0,
      "text": "# IANA-managed Reserved Domains\n...",
      "tokens": 987
    }
  ]
}
```

`max_tokens` controls the approximate size of **each** chunk, not the total amount of source retained. It must be between 100 and 50,000; the default is 6,000. Chunk boundaries preserve words and URLs, and fenced Markdown code blocks are kept intact when they fit within the requested budget. An oversized code block is split only within its body, with valid opening and closing fences restored to every resulting chunk.

Like the text endpoint, chunk mode retains up to 200,000 extracted characters. If that ceiling is reached, the response is truncated before chunking and returns `truncated: true` with `limiting_factor: "char_cap"`.

### Response fields

| Field | Meaning |
|---|---|
| `url` | Requested or resolved source URL. |
| `text` | Readable extracted text or Markdown. |
| `approx_tokens` | Approximate token count of `text`; calculated as `ceil(characters / 4)`. |
| `tokens` | Deprecated alias for `approx_tokens`; retained for backward compatibility. |
| `tokens_saved_estimate` | Approximate tokens saved relative to the fetched HTML; an estimate, not a billing figure. |
| `truncated` | `true` when a character or token limit shortened the returned content. |
| `limiting_factor` | Which limit applied: `char_cap`, `token_budget`, or `none`. |
| `cache_hit` | `true` when the response came from either cache layer. |
| `cache_layer` | `none`, `memory`, or `persistent`. |
| `low_yield` | `true` when a large page produced very little readable text. |
| `yield_hint` | Short explanation when `low_yield` is true. |
| `provenance` | Optional request, fetch, and cache metadata. |

### Common errors

Errors use a JSON `detail` object with `code`, `message`, and, when applicable, `hint`. For example, a missing or invalid key returns HTTP 401:

```json
{
  "detail": {
    "code": "invalid_api_key",
    "message": "A valid API key is required."
  }
}
```

An invalid or unsafe URL returns HTTP 400:

```json
{
  "detail": {
    "code": "invalid_or_unsafe_url",
    "message": "URL must be an absolute HTTP or HTTPS URL",
    "hint": "URL must start with http:// or https:// and be publicly accessible"
  }
}
```

| HTTP status | Error code(s) | What to do |
|---|---|---|
| 400 | `invalid_or_unsafe_url`, `render_js_disabled`, `invalid_token_budget` | Use a well-formed public HTTP or HTTPS URL. Private-network destinations are blocked. `render_js=true` is disabled unless the service enables it — retry with `render_js=false`. For chunk requests, `max_tokens` must be between 100 and 50,000. |
| 401 | `invalid_api_key` | Send the current `X-API-Key` configured in Render. |
| 500 | `auth_misconfiguration` | `REQUIRE_AUTH=true` is set (Render production default) but `API_KEY` and `RAPIDAPI_PROXY_SECRET` are both empty. Restore the secrets in the Render dashboard, then redeploy. |
| 413 | `payload_too_large` | The HTML exceeds 1 MiB after decompression. |
| 415 | `unsupported_media_type` | The target must return HTML or XHTML. |
| 429 | `burst_rate_limit_exceeded` | Pause for the seconds specified in the `Retry-After` response header, then retry. |
| 502 | `upstream_http_error`, `upstream_connection_error`, `upstream_render_error`, `unsupported_content_encoding`, or `too_many_redirects` | The target returned an error, could not be reached or rendered, used unsupported compression, or redirected too many times. |
| 504 | `upstream_timeout` | The target did not respond in time. |

The 429 response also includes a `Retry-After` header. Avoid repeatedly retrying 4xx responses; correct the request or wait as indicated.

## Run Locally

Use Python 3.12. Install the application and test dependencies, then start the service:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
uvicorn main:app --reload
```

The interactive API documentation is at `/docs`. With no keys configured, local development is open. Never deploy an unprotected instance; the Render blueprint generates an `API_KEY` by default.

### Docker

```powershell
docker build -t bintu-api .
docker run -p 8000:8000 -e API_KEY=your-key bintu-api
```

Or with Docker Compose:

```powershell
docker-compose up
```

## API

`GET /healthz` is a lightweight Render health check. It does not require authentication.

`GET /version` returns service configuration (no secrets exposed).

`GET /metrics` exposes Prometheus request counts, error counts, latency histograms, and cache hit/miss counters. Metrics use route templates rather than request URLs and do not include scraped content. Application request logs include a request ID, method, route template, status, and duration; they do not log target URLs or page text. The Render and Docker launch configurations disable Uvicorn access logs because access-log request lines can include the `url` query parameter. It is protected by the same credentials as the API, so send `X-API-Key` (or the RapidAPI proxy header) when a key is configured. `X-Request-ID` is returned on every response; valid caller-provided IDs are preserved, otherwise the API generates one.

`GET /api/v1/scrape/text?url=https%3A%2F%2Fexample.com` returns the requested URL, extracted text, and a `truncated` boolean. `truncated` is `true` only when extracted content exceeded the configured text limit. When available, the extractor prefers `<article>` or `<main>` content, then a `role="main"` or commonly named main/content container (such as `id="main"`), and otherwise falls back to the full document. It omits hidden elements and common controls or page furniture, and renders links as `link text (absolute URL)`. Headings are marked with Markdown `#` prefixes, paragraphs and other block elements are separated by line breaks, and table cells within each row are joined with ` | ` with a separator beneath header rows. If the document title duplicates its first heading, it is omitted. Character encoding is detected from the upstream HTTP charset and HTML metadata. Direct callers must send `X-API-Key` when `API_KEY` is configured. The endpoint supports public HTTP/HTTPS destinations only and does not bypass access controls.

`POST /api/v1/scrape/chunks` returns readable text as approximately token-budgeted chunks. It uses the same guarded fetching, extraction, authentication, caching, and rate limiting as `/api/v1/scrape/text`, but divides the extracted Markdown into ordered chunks using `max_tokens`.

JavaScript rendering is experimental. Keep `RENDER_JS_ENABLED=false`: the browser path has an unresolved DNS-rebinding time-of-check-to-time-of-use risk. Do not enable it until connection targeting, redirects, and browser subresource requests are hardened and tested. Paid infrastructure does not resolve this risk; see [Security Notes](SECURITY.md#javascript-rendering). When enabled, `render_js=true` selects headless Chromium rendering. Rendering waits for `networkidle`, validates browser-requested HTTP destinations against public DNS addresses, and omits images, media, and fonts to reduce memory use. Non-rendered requests retain the existing lightweight transport that pins each connection to a validated public IP. Both modes use the same extractor, text limits, persistent cache, authentication, and rate limiting.

`POST /mcp` is a standard MCP Streamable HTTP endpoint (stateless JSON-RPC 2.0) for Claude custom connectors and Claude Code: it answers `initialize`, `ping`, `tools/list`, and `tools/call` for the single `bintu_scrape_text` tool, and requires `Content-Type: application/json` plus the same API key as normal requests. Point a Claude custom connector at `https://<your-host>/mcp` with an `X-API-Key` request header. Notifications get `202`; `GET`/`DELETE` return `405` since the server keeps no sessions or streams.

`GET /mcp/tools` advertises the `bintu_scrape_text` tool, and `POST /mcp/tools/call` invokes it with `{"name":"bintu_scrape_text","arguments":{"url":"https://example.com","render_js":false}}`. Successful responses follow the MCP tool content shape and include the same extraction envelope as both structured content and serialized JSON: `structuredContent` contains the canonical extraction envelope, while `content[0].text` contains its JSON serialization. Tool calls use the same API authentication and rate limits as normal scrape requests.

### Query Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `url` | string | required | The URL to scrape |
| `render_js` | bool | false | Render JavaScript using headless Chromium before extracting |
| `include_nav` | bool | false | Preserve `<nav>` elements in output |
| `include_header` | bool | false | Preserve `<header>` elements in output |
| `include_footer` | bool | false | Preserve `<footer>` elements in output |

### Chunk Endpoint Parameters

`POST /api/v1/scrape/chunks` accepts the extraction fields in its JSON body and the following query parameters:

| Parameter | Type | Default | Description |
|---|---|---:|---|
| `max_tokens` | integer | 6000 | Approximate token budget for each chunk; must be 100–50,000 |
| `skip_cache` | bool | false | Bypass cached extraction and fetch the page again |
| `persist` | bool | true | Allow a successful extraction to be written to the persistent cache |

The JSON body accepts:

| Field | Type | Default | Description |
|---|---|---|---|
| `url` | string | required | Public HTTP or HTTPS URL to scrape |
| `include_nav` | bool | false | Preserve `<nav>` elements |
| `include_header` | bool | false | Preserve `<header>` elements |
| `include_footer` | bool | false | Preserve `<footer>` elements |
| `render_js` | bool | false | Request JavaScript rendering; disabled unless `RENDER_JS_ENABLED=true` |

### Service Limits

- Request timeout: 10 seconds per connection attempt.
- Redirects: at most 5, with URL and DNS validation repeated for every destination.
- HTML body: at most 1 MiB after decompression, read in chunks no larger than 4 KiB. Gzip-encoded HTML is supported with the same decoded-size limit.
- Text response: at most 6,000 characters; `truncated` is true when the content exceeds the limit. Truncated text ends at the last available word boundary.
- Chunk mode: retains up to 200,000 extracted characters before chunking. Each returned chunk is budgeted by `max_tokens` (100–50,000; default 6,000). Fenced code blocks are preserved when they fit and are split with restored fences when they do not.
- JavaScript rendering: disabled by default (`RENDER_JS_ENABLED=false`); `render_js=true` returns 400 `render_js_disabled`. Keep it disabled until the browser path is hardened and tested; paid infrastructure does not resolve the documented DNS-rebinding risk. See [Security Notes](SECURITY.md#javascript-rendering).
- Local abuse guard: 60 requests per client identity per 60 seconds, in process memory only. Behind Render, a client IP is honored only from Render's proxy range (`100.64.0.0/10`), so the guard cannot be bypassed by spoofing `X-Forwarded-For`. Set `REDIS_URL` to share the counter across instances; the window TTL is set once per window, and if Redis is unreachable the guard falls back to process memory rather than failing requests.
- Process-local HTML cache: 5-minute TTL, bounded to 64 entries per instance with least-recently-used eviction. `CACHE_TTL_SECONDS=0` disables this local cache. When configured, the separate Supabase Markdown cache retains successful extractions for 24 hours.
- Paid subscription quotas and billing: configured and enforced by RapidAPI, not by this service.

## Configuration

| Environment Variable | Default | Description |
|---|---|---|
| `API_KEY` | (empty) | API key for direct access |
| `RAPIDAPI_PROXY_SECRET` | (empty) | Secret for RapidAPI proxy authentication |
| `SUPABASE_URL` | (empty) | Supabase project URL used to verify mobile user sessions |
| `SUPABASE_ANON_KEY` | (empty) | Supabase publishable/anon key used for mobile session verification; never use a service-role/secret key |
| `SUPABASE_SERVICE_ROLE_KEY` | (empty) | Private server-side key for persistent scrape caching and RapidAPI usage accounting |
| `CACHE_TTL_SECONDS` | 300 | Process-local HTML cache TTL in seconds; `0` disables that cache (Supabase's 24-hour cache is separate). Non-numeric or out-of-range values (allowed range 0-86400) fall back to 300 with a logged warning |
| `REDIS_URL` | (empty) | Redis URL for multi-instance rate limiting. Empty or unreachable = per-process burst guard (fail-open), each instance enforcing its own window |
| `RENDER_JS_ENABLED` | `false` | JavaScript rendering kill-switch. Keep `false` until the browser path is hardened and tested; see [Security Notes](SECURITY.md#javascript-rendering). Only exact `true` enables Chromium; anything else returns 400 `render_js_disabled` for `render_js=true` |
| `BINTU_UPGRADE_URL` | `https://mcpize.com` | Canonical subscribe URL embedded in MCP 401 `-32001` `upgrade_url` so agents print a clickable link in-chat |

## Deploy To Render

1. Push this project to a GitHub repository.
2. In Render, create a new Blueprint and select that repository. Render reads `render.yaml`, installs `requirements.txt` and Chromium's system dependencies, then starts Uvicorn on the assigned port.
3. Wait for `/healthz` to pass. Copy the generated `API_KEY` from the service environment for direct API access. Do not commit either secret.
4. Test the deployed `/docs` page and make an authenticated scrape request before publishing.

The free instance can sleep while idle, so the first request may be slow. Free services are best for validation and early users, not latency-sensitive production or an uptime guarantee. The local burst guard resets on restarts and is not shared across instances. It is not a paid quota; use RapidAPI plan limits as the billing authority.

## Storefront parity (single source of truth)

One API, three doors. Behaviour is identical; only auth + billing differ per gateway:

| | Direct (Render) | RapidAPI | MCPize |
|---|---|---|---|
| Listing name | Service `bintu-data-extraction-api` (MCP `serverInfo.name: bintu`) | `Bintu Data Extraction API` (subdomain `bintu-data-extraction-api`) | **LLM Web Scraper & Clean Text Extractor** (slug/host `bintu-web-reader.mcpize.run`; users label their Claude connector `Bintu-web-reader`) |
| Endpoint | `GET /api/v1/scrape/text?url=…` at `https://bintu-api.onrender.com` | Same path at `https://bintu-data-extraction-api.p.rapidapi.com` | `bintu_scrape_text` tool at `https://bintu-web-reader.mcpize.run` (upstream `POST https://bintu-api.onrender.com/mcp`) |
| Auth | `X-API-Key: <Render API_KEY>` | `X-RapidAPI-Key` + `X-RapidAPI-Host` (gateway injects `X-RapidAPI-Proxy-Secret` + `X-RapidAPI-User`) | Subscriber's MCPize key (`sk_…`); gateway injects the upstream `X-API-Key`. Never send buyers to RapidAPI from the MCPize page |
| Billing | None (owner key) | RapidAPI plans: BASIC $0/100 · PRO $9/10k · ULTRA $29/50k · MEGA $79/100k+ | MCPize publisher tiers (dashboard → Monetize): Free ~1k · Pro $9–19 · Team $49+ (80% via Stripe Connect) |
| Quota | 60 req / 60 s burst guard per IP | 60/60s per `X-RapidAPI-User` + plan quota | 60/60s global across MCPize subscribers (single upstream token) + plan quota |
| Cache | 5-min in-memory + 24 h Supabase persistent | Same | Same upstream cache; cold fetch ~2–6 s, cache hit ~300 ms |

**Token Tax positioning (MCP):** `bintu_scrape_text` is a Token-Sanitized Context Gateway — nav/ads/footer stripped, deterministic `max_tokens` chunks (`chunked→chunk`, `chunk_token_budget→max_tokens` aliases), every mode returns the unified JSON envelope `core fields `mode`, `tokens`, `approx_tokens`, `html_tokens`, `token_method`, `limiting_factor`, `chunk_count`, `cache_hit`, `cache_layer`, `source_url`, `extracted_at`, `tokens_saved_estimate`, `truncated`, `split`, and `chunks`` in `content[0].text` plus `X-Token-Usage` header and 401 `-32001` `upgrade_url` (`https://mcpize.com`, override `BINTU_UPGRADE_URL`). No tier caps in code — dashboards own quota. New env: `BINTU_UPGRADE_URL` (default `https://mcpize.com`).

### Section selection

For `mode=scrape`, supply `sections` to return only selected Markdown
sections instead of the full extracted page.

MCP accepts either an array of strings or newline-separated selectors:

```json
{
  "name": "bintu_scrape_text",
  "arguments": {
    "url": "[https://example.com](https://example.com)",
    "sections": ["Alpha", "Beta"]
  }
}
```

```json
{
  "name": "bintu_scrape_text",
  "arguments": {
    "url": "[https://example.com](https://example.com)",
    "sections": "Alpha\nBeta"
  }
}
```

REST accepts repeated `sections` query parameters:

```http
GET /api/v1/scrape/text?url=https%3A%2F%2Fexample.com&sections=Alpha&sections=Beta
```

Selectors are matched exactly against normalized Markdown heading text:
whitespace is collapsed and matching is case-insensitive. Each selector
must be 200 characters or fewer. Empty or whitespace-only selectors return
`invalid_arguments`.

When `sections` is supplied, cache reads are bypassed so selection uses
freshly extracted Markdown. A fresh result may still be written to the
persistent cache when `persist=true`.

The response includes `selected_sections` only for scrape requests that
supply selectors. Each selected section contains:

| Field | Meaning |
|---|---|
| `heading` | Original heading text |
| `level` | Markdown heading level, 1–6 |
| `index` | Zero-based position of the heading in the document’s full heading sequence |
| `text` | Selected section body after sequential token-budget clipping |

If no heading matches, `selected_sections` is an empty array, `text` is
empty, and `low_yield` is `false`.

`max_tokens` applies to the combined selected text. When the budget is
exceeded, sections are clipped sequentially in document order,
`truncated` becomes `true`, and `limiting_factor` becomes
`token_budget`.

### Chunk mode limits

Chunk mode preserves up to 200,000 extracted characters, approximately
50,000 tokens under `ceil(characters / 4)`.

`max_tokens` controls the approximate size of each emitted chunk, not the
total amount of source retained. Sources larger than the extraction ceiling
are truncated before chunking and return `truncated: true` with
`limiting_factor: "char_cap"`.

Fenced Markdown code blocks are treated as atomic when they fit within a
chunk budget. Oversized fenced blocks are split only within the code body;
each resulting chunk receives restored opening and closing fences, keeping
every chunk valid, self-contained Markdown.

Legacy scrape endpoint limits: 1 MiB upstream body, HTML/XHTML only, 6,000-char text cap (`truncated` flag), 5 redirects, `render_js=true` → 400 `render_js_disabled` (keep `RENDER_JS_ENABLED=false` until browser security hardening is complete; paid infrastructure does not resolve the risk). Error codes: see [Common errors](#common-errors).

## Usage examples

Ready-to-run clients are in [`examples/`](./examples):

- [`rest_python.py`](./examples/rest_python.py) ? REST extraction with Python
- [`rest_javascript.js`](./examples/rest_javascript.js) ? REST extraction with Node.js
- [`mcp_python.py`](./examples/mcp_python.py) ? MCP `tools/call` with Python

Set your credentials first:

```powershell
$env:BINTU_BASE_URL = "[https://bintu-api.onrender.com](https://bintu-api.onrender.com)"
$env:BINTU_API_KEY = Read-Host "Paste API key"
```

Then run:

```powershell
python .\examples\rest_python.py [https://example.com](https://example.com)
node .\examples\rest_javascript.js [https://example.com](https://example.com)
python .\examples\mcp_python.py [https://example.com](https://example.com)
```

## RapidAPI Publishing

RapidAPI handles subscriber authentication and billing at its gateway. In the RapidAPI provider dashboard, point the API base URL at the Render service and configure the provider proxy secret. Set Render's `RAPIDAPI_PROXY_SECRET` to the same value. Requests authenticated with `X-RapidAPI-Proxy-Secret` are accepted; their `X-RapidAPI-User` identity receives an independent 60-request-per-minute bucket. Keep `API_KEY` for owner/direct access, and never expose either secret in client examples.

Configure subscription plans, monthly quotas, and pricing in RapidAPI. Start with a small free trial and paid tiers based on measured Render latency, failure rates, and upstream costs. The service's 60-per-minute guard is a burst limit, not a monthly quota or billing system. Marketplace placement and revenue are not guaranteed.

Only scrape content you are authorized to access. Respect the target site's terms and robots policy. This API does not circumvent logins, CAPTCHAs, paywalls, or anti-bot controls.

### Connect Claude

`POST /mcp` implements the standard MCP Streamable HTTP transport (protocol `2025-11-25`, also accepting `2025-06-18`/`2025-03-26`), so any MCP client can call the scraper. It is stateless: no `Mcp-Session-Id` is issued, `GET` answers with an empty SSE stream (`GET /sse` and `GET /mcp/sse` are compatibility aliases for gateways that probe a dedicated SSE path), `DELETE`/`PUT`/`PATCH` return `405`, and each JSON-RPC message is answered with a single `application/json` response. Requests after `initialize` must carry the negotiated `MCP-Protocol-Version` header (unknown versions get `400`), and a mismatched `Origin` header is rejected with `403` against DNS rebinding. `initialize`, `tools/list`, and `ping` are public discovery methods (protocol negotiation, tool schemas, liveness — no extraction), so gateway health-checkers, marketplace audits, and Claude Web — none of which can send headers during onboarding — complete instantly; `tools/call` and every other method require `X-API-Key` or `Authorization: Bearer` with the scoped `MCP_API_KEY` or the master `API_KEY`, and a missing or invalid credential on an execution call answers `401` with `{"code": "invalid_api_key", "message": "A premium subscription or valid X-API-Key is required to execute scrapes."}` while all billable work stays behind auth.

- Direct — Claude web or Desktop: custom connector URL `https://bintu-api.onrender.com/mcp` with request header `X-API-Key: <MCP_API_KEY>`.
- Direct — Claude Code: `claude mcp add --transport http bintu https://bintu-api.onrender.com/mcp --header "X-API-Key: <MCP_API_KEY>"`.
- MCPize (subscribers): connect to `https://bintu-web-reader.mcpize.run` with your MCPize `sk_…` key — the gateway injects the upstream token. No RapidAPI subscription needed; billing lives on the MCPize listing.

`MCP_API_KEY` is the optional scoped key set in the Render dashboard. It is accepted only on the MCP surfaces (`/mcp`, `/mcp/tools`, `/mcp/tools/call`) and never on the REST routes or `/metrics`, so it can be shared with connector users and rotated without touching the master `API_KEY`. While `MCP_API_KEY` is unset, the master `API_KEY` keeps working on `/mcp` exactly as before.

The server exposes one tool, `bintu_scrape_text`, with the same schema as the REST scrape. Tool execution failures (unsafe URL, rate limit, upstream error, `render_js_disabled`) come back in-band as `isError: true` with readable text so the model can correct itself. Execution requests (`tools/call`) require a valid key (the master `API_KEY` or the scoped `MCP_API_KEY`, via `X-API-Key` or `Authorization: Bearer`) and count against the same rate limit; discovery (`initialize`, `tools/list`, `ping`) needs no credentials. This endpoint is hidden from `/docs`; see the MCP section of the README.

## Native Mobile MVP

The Expo project in `mobile-app/` provides email sign-up/sign-in and a URL-to-readable-text screen for iOS and Android. User sessions are stored with the device's secure storage. The app sends its Supabase access token to `POST /api/v1/mobile/scrape/text`; the API verifies the user with Supabase, requires a verified email address, and applies the existing per-user burst limit. The Bintu `API_KEY` and RapidAPI provider secret are never sent to the app.

### Configure the backend

1. Create a Supabase project and enable email/password authentication. Keep email confirmation enabled.
2. In Supabase project settings, copy the project URL and its publishable key (or legacy anon key). Do not use the `service_role` key or a secret key.
3. Set `SUPABASE_URL` and `SUPABASE_ANON_KEY` in the Render service environment. Keep the existing generated `API_KEY` private.
4. To enable persistent scraping cache and RapidAPI usage counts, set the server-only `SUPABASE_SERVICE_ROLE_KEY` in Render. Run [`supabase_schema.sql`](./supabase_schema.sql) in the Supabase SQL editor to create the required tables and atomic usage-increment function. Never include the service-role key in the mobile app. Without this key, scraping continues with the existing bounded in-memory cache and database features are disabled.

The persistent cache retains successful Markdown for 24 hours. Cache keys include the URL, rendering mode, and extraction options, and expired entries are ignored. RapidAPI usage counts are incremented only for requests carrying a valid configured RapidAPI proxy secret and a valid `X-RapidAPI-User` header; cached successful calls are counted too. Database failures are logged and fall back to scraping or return the successfully extracted content.

The mobile proxy remains unavailable until both Supabase settings are configured. Supabase must be reachable by the API at request time so the API can verify each session.

In Supabase **Authentication → URL Configuration → Redirect URLs**, allow the Expo Go callback `exp://**/--/auth/callback` and the installed-app callback `bintu://**`. The app sends an explicit callback URL for sign-up confirmation and password recovery, so those links open Bintu instead of the default `localhost:3000`. Expo Go redirects only work while the development server is running and reachable on the phone's network.

### Run on an Android phone

Install a current Node.js LTS release, install Expo Go on an Android phone, and from the `mobile-app/` directory:

```powershell
Copy-Item .env.example .env
# Edit .env and set the Supabase project URL and publishable/anon key.
npm install
node .\node_modules\expo\bin\cli start
```

Scan the QR code shown by Expo Go. The app handles confirmation and password-reset links and lets the user set a new password after following a recovery link. The `EXPO_PUBLIC_` Supabase key is a client/public key, not a service secret; the API verifies sessions and keeps the Bintu server key private. A local `.env` file is git-ignored. iOS simulator builds require macOS and Xcode; public app-store distribution has separate developer enrollment requirements and fees.

This is an early MVP: the API's in-memory limiter resets on restart and does not provide account-abuse prevention or a monthly user quota. Review hosting and Supabase plan limits before inviting more users.

## REST document reader

The reader provides paginated access to a retained text snapshot through
`POST /api/v1/reader/read` and `POST /api/v1/reader/continue`. These routes
are separate from the existing scrape endpoints and are not exposed as
new MCP tools. They become available when a version containing this
change is deployed.

### Authentication and ownership

Both endpoints require either the configured direct `API_KEY` in
`X-API-Key`, or a verified RapidAPI proxy request with a valid
`X-RapidAPI-User`. Unauthenticated local development mode does not grant
reader access.

Ownership is credential-level: all callers using the same direct API key
share one owner identity. Verified RapidAPI subscribers have separate
owner identities. An unverified subscriber header does not establish
ownership. Mobile Supabase sessions and the scoped `MCP_API_KEY` are not
reader credentials.

Treat continuation cursors as sensitive, temporary handles. Use the same
authenticated owner for the initial read and subsequent continuations.

### Read and continue

For local testing, start the application with an `API_KEY` configured,
and set that same key in `$env:BINTU_API_KEY`. Use a deployed base URL
only after the reader changes have been deployed.

```powershell
$readerBaseUrl = "http://127.0.0.1:8000"
$headers = @{ "X-API-Key" = $env:BINTU_API_KEY }

$body = @{
    url = "https://www.iana.org/domains/reserved"
    max_tokens = 1000
    include_nav = $false
    include_header = $false
    include_footer = $false
} | ConvertTo-Json

$page = Invoke-RestMethod `
    -Method Post `
    -Uri "$readerBaseUrl/api/v1/reader/read" `
    -Headers $headers `
    -ContentType "application/json" `
    -Body $body

$page.text

while ($page.has_more) {
    $body = @{
        cursor = $page.next_cursor
        max_tokens = 1000
    } | ConvertTo-Json

    $page = Invoke-RestMethod `
        -Method Post `
        -Uri "$readerBaseUrl/api/v1/reader/continue" `
        -Headers $headers `
        -ContentType "application/json" `
        -Body $body

    $page.text
}
```

The initial request checks robots policy, fetches the page using the
existing guarded fetcher, and extracts a text snapshot. Continuations
read that snapshot without refetching the target. Pages therefore
represent the original extraction, not subsequent website changes.

`max_tokens` must be a JSON integer from 100 through 50000; it defaults to
1000 on each request. It budgets page text only, not JSON framing,
metadata, or other model context. A larger budget raises the effective
extraction cap above the 6,000-character default, subject to a 200,000
character absolute ceiling. The response includes `approx_tokens` and
`token_method`; do not treat the estimate as an exact count for every
model tokenizer.

Responses include `text`, `start_offset`, `end_offset`, `has_more`,
`next_cursor`, `approx_tokens`, `token_method`, `boundary_split`, and
`budget_scope` (`page_text_only`). Continue using the returned cursor,
not a client-supplied offset. The final page has `has_more=false` and
`next_cursor=null`. The three extraction inclusion flags default to
false and are set only on the initial request.

### Retention and deployment limits

The reader retains at most 200,000 extracted text characters per document.
It rejects larger extracted documents instead of silently shortening them. Its retention limit is separate from the legacy scrape
response character limit; upstream fetch size and media-type guards
still apply.

The application's default snapshot store has:

- A fixed 600-second lifetime from snapshot creation. Reads do not
  extend it.
- Capacity for 16 retained documents and 256 continuation handles per
  application store.
- Oldest-inserted eviction when either capacity is exceeded.
- Process-local memory only: snapshots are not persisted or shared
  between workers or instances, and disappear on restart.

Ten minutes is an expiry limit, not a guaranteed availability window:
eviction can invalidate a cursor sooner. A continuation sent to another
worker or instance cannot resolve the original worker's cursor.
Multi-worker or multi-instance deployments need an explicit routing or
shared-storage design before reliable continuation can be promised.

Unknown, expired, evicted, and wrong-owner cursors all return HTTP 404
with `detail.code=reader_snapshot_unavailable`. Start a new read to
recover; doing so fetches the target again and may produce different
text.

Both initial reads and continuations pass through the rate limiter.
Successful verified RapidAPI requests on either endpoint attempt a
developer usage increment when the database client is available.
Database usage-recording failures do not fail an otherwise successful
reader response. This accounting is not a replacement for gateway plan
quotas.

### Observability

Reader requests pass through the existing HTTP observability
middleware: request count, error count, duration, request-completion
logs, and the `X-Request-ID` response header.

The reader route implementation does not call the existing
extraction-completion and extraction-failure metric helpers. Do not
interpret those extraction-specific metrics as complete reader usage
or failure coverage.

## Tests

The suite lives in the tests/ package and is offline: it patches connections and uses fake responses, so it makes no live network requests.

```powershell
python -m unittest discover -s tests -t . -p "test_*.py" -v
```

Integration tests run a real local HTTP server on a loopback port to exercise the full fetch, parse, and extract pipeline, with DNS resolution and connection targeting mocked so the SSRF guards still apply:

```powershell
python -m unittest tests.test_integration -v
```

Chunking is covered by offline unit tests for token budgets, word boundaries, and fenced-code preservation, plus endpoint tests for token-budget validation, disabled JavaScript rendering, and successful chunked responses.

The synthetic golden fixtures in `tests/fixtures/extraction_quality/` cover article, navigation-heavy, and table-heavy HTML without relying on third-party sites. Update a fixture and its expected `.txt` output only after reviewing an intentional extraction change.

GitHub Actions runs the offline test suite for pushes and pull requests. Render is configured to deploy linked commits only after CI checks pass. After deploying, verify real upstream fetching with `python -m scripts.smoke_check` (set `BINTU_BASE_URL` and `BINTU_API_KEY`); mocked tests cannot catch upstream HTTP regressions on their own.

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) for local setup, tests, live smoke checks, and contribution expectations.

## Operations

See [docs/OPERATIONS.md](./docs/OPERATIONS.md) for deployment checks, monitoring, incident response, and credential rotation.

## Support

See [docs/SUPPORT.md](./docs/SUPPORT.md) for troubleshooting authentication, URL restrictions, rate limits, truncation, low-yield pages, and upstream failures.

## API reference

See [docs/API_REFERENCE.md](./docs/API_REFERENCE.md) for the consolidated REST and MCP endpoint reference, request fields, response fields, limits, and error codes.
