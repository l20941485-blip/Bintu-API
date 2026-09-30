# Bintu Data Extraction API

A small FastAPI service that extracts readable text from public HTML pages. It limits upstream responses to 1 MiB, accepts HTML/XHTML only, pins outbound connections to validated public IPs, and applies a 60-request per-minute process-local burst limit.

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

`GET /metrics` exposes Prometheus request counts, error counts, latency histograms, and cache hit/miss counters. It is protected by the same credentials as the API, so send `X-API-Key` (or the RapidAPI proxy header) when a key is configured. `X-Request-ID` is returned on every response; valid caller-provided IDs are preserved, otherwise the API generates one.

`GET /api/v1/scrape/text?url=https%3A%2F%2Fexample.com` returns the requested URL and extracted text. Direct callers must send `X-API-Key` when `API_KEY` is configured. The endpoint supports public HTTP/HTTPS destinations only. It does not execute JavaScript or bypass access controls.

### Query Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `url` | string | required | The URL to scrape |
| `include_nav` | bool | false | Preserve `<nav>` elements in output |
| `include_header` | bool | false | Preserve `<header>` elements in output |
| `include_footer` | bool | false | Preserve `<footer>` elements in output |

### Error Responses

Expected errors use a structured `detail` object with `code`, `message`, and optional `hint` fields. Common status codes are 400 for invalid URLs, 401 for invalid credentials, 413 for pages above 1 MiB, 415 for non-HTML content, 429 for the local burst guard, 502 for target HTTP/connection failures, and 504 for target timeouts. Every 429 response carries a `Retry-After` header so well-behaved clients can back off.

### Service Limits

- Request timeout: 10 seconds per connection attempt.
- Redirects: at most 5, with URL and DNS validation repeated for every destination.
- HTML body: at most 1 MiB, read in chunks no larger than 4 KiB.
- Text response: at most 6,000 characters.
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

GitHub Actions runs the offline test suite for pushes and pull requests. Render is configured to deploy linked commits only after CI checks pass. After deploying, verify real upstream fetching with `python smoke_check.py` (set `BINTU_BASE_URL` and `BINTU_API_KEY`); mocked tests cannot catch upstream HTTP regressions on their own.
