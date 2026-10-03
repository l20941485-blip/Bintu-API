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

The Render `API_KEY` is available in the service's Environment settings. Keep it private, do not commit it, and do not put it in a URL. The examples above keep it in the current PowerShell process environment. If no API key or proxy secret is configured (as in the default local development setup), authentication is not required. Interactive API docs are available at [`/docs`](https://bintu-api.onrender.com/docs).

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
| 400 | `invalid_or_unsafe_url` | Use a well-formed public HTTP or HTTPS URL. Private-network destinations are blocked. |
| 401 | `invalid_api_key` | Send the current `X-API-Key` configured in Render. |
| 413 | `payload_too_large` | The HTML exceeds 1 MiB after decompression. |
| 415 | `unsupported_media_type` | The target must return HTML or XHTML. |
| 429 | `burst_rate_limit_exceeded` | Pause for the seconds specified in the `Retry-After` response header, then retry. |
| 502 | `upstream_http_error`, `upstream_connection_error`, `unsupported_content_encoding`, or `too_many_redirects` | The target returned an error, could not be reached, used unsupported compression, or redirected too many times. |
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

`GET /api/v1/scrape/text?url=https%3A%2F%2Fexample.com` returns the requested URL, extracted text, and a `truncated` boolean. `truncated` is `true` only when extracted content exceeded the configured text limit. When available, the extractor prefers `<article>` content, then `<main>`, and otherwise falls back to the full document. It omits hidden elements and common controls or page furniture, and renders links as `link text (absolute URL)`. Headings are marked with Markdown `#` prefixes, paragraphs and other block elements are separated by line breaks, and table cells within each row are joined with ` | ` with a separator beneath header rows. If the document title duplicates its first heading, it is omitted. Character encoding is detected from the upstream HTTP charset and HTML metadata. Direct callers must send `X-API-Key` when `API_KEY` is configured. The endpoint supports public HTTP/HTTPS destinations only. It does not execute JavaScript or bypass access controls.

### Query Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `url` | string | required | The URL to scrape |
| `include_nav` | bool | false | Preserve `<nav>` elements in output |
| `include_header` | bool | false | Preserve `<header>` elements in output |
| `include_footer` | bool | false | Preserve `<footer>` elements in output |

### Service Limits

- Request timeout: 10 seconds per connection attempt.
- Redirects: at most 5, with URL and DNS validation repeated for every destination.
- HTML body: at most 1 MiB after decompression, read in chunks no larger than 4 KiB. Gzip-encoded HTML is supported with the same decoded-size limit.
- Text response: at most 6,000 characters; `truncated` is true when the content exceeds the limit. Truncated text ends at the last available word boundary.
- Local abuse guard: 60 requests per client identity per 60 seconds, in process memory only. Behind Render, a client IP is honored only from Render's proxy range (`100.64.0.0/10`), so the guard cannot be bypassed by spoofing `X-Forwarded-For`. Set `REDIS_URL` to share the counter across instances; the window TTL is set once per window, and if Redis is unreachable the guard falls back to process memory rather than failing requests.
- Cache: 5-minute TTL for successful responses, bounded to 64 entries per instance with least-recently-used eviction, so memory stays bounded even when callers keep requesting novel URLs. `CACHE_TTL_SECONDS=0` disables caching.
- Paid subscription quotas and billing: configured and enforced by RapidAPI, not by this service.

## Configuration

| Environment Variable | Default | Description |
|---|---|---|
| `API_KEY` | (empty) | API key for direct access |
| `RAPIDAPI_PROXY_SECRET` | (empty) | Secret for RapidAPI proxy authentication |
| `CACHE_TTL_SECONDS` | 300 | Cache TTL in seconds; `0` disables caching. Non-numeric or out-of-range values (allowed range 0-86400) fall back to 300 with a logged warning |
| `REDIS_URL` | (empty) | Redis URL for multi-instance rate limiting |

## Deploy To Render

1. Push this project to a GitHub repository.
2. In Render, create a new Blueprint and select that repository. Render reads `render.yaml`, installs `requirements.txt`, and starts Uvicorn on the assigned port.
3. Wait for `/healthz` to pass. Copy the generated `API_KEY` from the service environment for direct API access. Do not commit either secret.
4. Test the deployed `/docs` page and make an authenticated scrape request before publishing.

The free instance can sleep while idle, so the first request may be slow. Free services are best for validation and early users, not latency-sensitive production or an uptime guarantee. The local burst guard resets on restarts and is not shared across instances. It is not a paid quota; use RapidAPI plan limits as the billing authority.

## RapidAPI Publishing

RapidAPI handles subscriber authentication and billing at its gateway. In the RapidAPI provider dashboard, point the API base URL at the Render service and configure the provider proxy secret. Set Render's `RAPIDAPI_PROXY_SECRET` to the same value. Requests authenticated with `X-RapidAPI-Proxy-Secret` are accepted; their `X-RapidAPI-User` identity receives an independent 60-request-per-minute bucket. Keep `API_KEY` for owner/direct access, and never expose either secret in client examples.

Configure subscription plans, monthly quotas, and pricing in RapidAPI. Start with a small free trial and paid tiers based on measured Render latency, failure rates, and upstream costs. The service's 60-per-minute guard is a burst limit, not a monthly quota or billing system. Marketplace placement and revenue are not guaranteed.

Only scrape content you are authorized to access. Respect the target site's terms and robots policy. This API does not circumvent logins, CAPTCHAs, paywalls, or anti-bot controls.

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
