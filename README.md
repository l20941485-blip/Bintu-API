# Bintu Data Extraction API

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
| 400 | `invalid_or_unsafe_url`, `render_js_disabled` | Use a well-formed public HTTP or HTTPS URL. Private-network destinations are blocked. `render_js=true` is disabled unless the service enables it — retry with `render_js=false`. |
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
cd "Bintu API"
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

Add `render_js=true` to opt in to headless Chromium rendering for JavaScript-driven pages. Rendering waits for `networkidle`, validates browser-requested HTTP destinations against public DNS addresses, and omits images, media, and fonts to reduce memory use. Non-rendered requests retain the existing lightweight transport that pins each connection to a validated public IP. Both modes use the same extractor, text limits, persistent cache, authentication, and rate limiting.

`POST /mcp` is a standard MCP Streamable HTTP endpoint (stateless JSON-RPC 2.0) for Claude custom connectors and Claude Code: it answers `initialize`, `ping`, `tools/list`, and `tools/call` for the single `bintu_scrape_text` tool, and requires `Content-Type: application/json` plus the same API key as normal requests. Point a Claude custom connector at `https://<your-host>/mcp` with an `X-API-Key` request header. Notifications get `202`; `GET`/`DELETE` return `405` since the server keeps no sessions or streams.

`GET /mcp/tools` advertises the `bintu_scrape_text` tool, and `POST /mcp/tools/call` invokes it with `{"name":"bintu_scrape_text","arguments":{"url":"https://example.com","render_js":false}}`. The response follows the MCP tool content shape: `{"content":[{"type":"text","text":"..."}]}`. Tool calls use the same API authentication and rate limits as normal scrape requests.

### Query Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `url` | string | required | The URL to scrape |
| `render_js` | bool | false | Render JavaScript using headless Chromium before extracting |
| `include_nav` | bool | false | Preserve `<nav>` elements in output |
| `include_header` | bool | false | Preserve `<header>` elements in output |
| `include_footer` | bool | false | Preserve `<footer>` elements in output |

### Service Limits

- Request timeout: 10 seconds per connection attempt.
- Redirects: at most 5, with URL and DNS validation repeated for every destination.
- HTML body: at most 1 MiB after decompression, read in chunks no larger than 4 KiB. Gzip-encoded HTML is supported with the same decoded-size limit.
- Text response: at most 6,000 characters; `truncated` is true when the content exceeds the limit. Truncated text ends at the last available word boundary.
- JavaScript rendering: disabled by default (`RENDER_JS_ENABLED=false`); `render_js=true` returns 400 `render_js_disabled`. Enable only on paid infra where Chromium boot cost is covered.
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
| `RENDER_JS_ENABLED` | `false` | JavaScript rendering kill-switch. Only exact `true` enables Chromium; anything else returns 400 `render_js_disabled` for `render_js=true` |

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
| Endpoint | `GET /api/v1/scrape/text?url=…` at `https://bintu-api.onrender.com` | Same path at `https://bintu-data-extraction-api.p.rapidapi.com` | `bintu_scrape_text` tool at `https://bintu-web-reader.mcpize.run` (upstream `POST https://bintu-api.onrender.com/mcp`) |
| Auth | `X-API-Key: <Render API_KEY>` | `X-RapidAPI-Key` + `X-RapidAPI-Host` (gateway injects `X-RapidAPI-Proxy-Secret` + `X-RapidAPI-User`) | Subscriber's MCPize key (`sk_…`); gateway injects the upstream `X-API-Key`. Never send buyers to RapidAPI from the MCPize page |
| Billing | None (owner key) | RapidAPI plans: BASIC $0/100 · PRO $9/10k · ULTRA $29/50k · MEGA $79/100k+ | MCPize publisher tiers (dashboard → Monetize): Free ~1k · Pro $9–19 · Team $49+ (80% via Stripe Connect) |
| Quota | 60 req / 60 s burst guard per IP | 60/60s per `X-RapidAPI-User` + plan quota | 60/60s global across MCPize subscribers (single upstream token) + plan quota |
| Cache | 5-min in-memory + 24 h Supabase persistent | Same | Same upstream cache; cold fetch ~2–6 s, cache hit ~300 ms |

Limits everywhere: 1 MiB upstream body, HTML/XHTML only, 6,000-char text cap (`truncated` flag), 5 redirects, `render_js=true` → 400 `render_js_disabled` (plain HTML only until `RENDER_JS_ENABLED=true` on paid infra). Error codes: see [Common errors](#common-errors).

## RapidAPI Publishing

RapidAPI handles subscriber authentication and billing at its gateway. In the RapidAPI provider dashboard, point the API base URL at the Render service and configure the provider proxy secret. Set Render's `RAPIDAPI_PROXY_SECRET` to the same value. Requests authenticated with `X-RapidAPI-Proxy-Secret` are accepted; their `X-RapidAPI-User` identity receives an independent 60-request-per-minute bucket. Keep `API_KEY` for owner/direct access, and never expose either secret in client examples.

Configure subscription plans, monthly quotas, and pricing in RapidAPI. Start with a small free trial and paid tiers based on measured Render latency, failure rates, and upstream costs. The service's 60-per-minute guard is a burst limit, not a monthly quota or billing system. Marketplace placement and revenue are not guaranteed.

Only scrape content you are authorized to access. Respect the target site's terms and robots policy. This API does not circumvent logins, CAPTCHAs, paywalls, or anti-bot controls.

### Connect Claude

`POST /mcp` implements the standard MCP Streamable HTTP transport (protocol `2025-11-25`, also accepting `2025-06-18`/`2025-03-26`), so any MCP client can call the scraper. It is stateless: no `Mcp-Session-Id` is issued, `GET` answers with an empty SSE stream (`GET /sse` and `GET /mcp/sse` are compatibility aliases for gateways that probe a dedicated SSE path), `DELETE`/`PUT`/`PATCH` return `405`, and each JSON-RPC message is answered with a single `application/json` response. Requests after `initialize` must carry the negotiated `MCP-Protocol-Version` header (unknown versions get `400`), and a mismatched `Origin` header is rejected with `403` against DNS rebinding. `initialize` is a public capability handshake (protocol version + tool names only, no extraction); `tools/list` and `tools/call` require auth, so gateway health-checkers that omit the upstream token can validate the endpoint while all billable work stays behind auth.

- Direct — Claude web or Desktop: custom connector URL `https://bintu-api.onrender.com/mcp` with request header `X-API-Key: <MCP_API_KEY>`.
- Direct — Claude Code: `claude mcp add --transport http bintu https://bintu-api.onrender.com/mcp --header "X-API-Key: <MCP_API_KEY>"`.
- MCPize (subscribers): connect to `https://bintu-web-reader.mcpize.run` with your MCPize `sk_…` key — the gateway injects the upstream token. No RapidAPI subscription needed; billing lives on the MCPize listing.

`MCP_API_KEY` is the optional scoped key set in the Render dashboard. It is accepted only on the MCP surfaces (`/mcp`, `/mcp/tools`, `/mcp/tools/call`) and never on the REST routes or `/metrics`, so it can be shared with connector users and rotated without touching the master `API_KEY`. While `MCP_API_KEY` is unset, the master `API_KEY` keeps working on `/mcp` exactly as before.

The server exposes one tool, `bintu_scrape_text`, with the same schema as the REST scrape. Tool execution failures (unsafe URL, rate limit, upstream error, `render_js_disabled`) come back in-band as `isError: true` with readable text so the model can correct itself. All requests still require a valid key (the master `API_KEY` or the scoped `MCP_API_KEY`) and count against the same rate limit. This endpoint is hidden from `/docs`; see the MCP section of the README.

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

## Tests

The suite lives in the tests/ package and is offline: it patches connections and uses fake responses, so it makes no live network requests.

```powershell
python -m unittest discover -s tests -t . -p "test_*.py" -v
```

Integration tests run a real local HTTP server on a loopback port to exercise the full fetch, parse, and extract pipeline, with DNS resolution and connection targeting mocked so the SSRF guards still apply:

```powershell
python -m unittest tests.test_integration -v
```

The synthetic golden fixtures in `tests/fixtures/extraction_quality/` cover article, navigation-heavy, and table-heavy HTML without relying on third-party sites. Update a fixture and its expected `.txt` output only after reviewing an intentional extraction change.

GitHub Actions runs the offline test suite for pushes and pull requests. Render is configured to deploy linked commits only after CI checks pass. After deploying, verify real upstream fetching with `python smoke_check.py` (set `BINTU_BASE_URL` and `BINTU_API_KEY`); mocked tests cannot catch upstream HTTP regressions on their own.
