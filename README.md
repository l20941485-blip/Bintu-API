# Bintu Data Extraction API

A small FastAPI service that extracts readable text from public HTML pages. It limits upstream responses to 1 MiB, accepts HTML/XHTML only, pins outbound connections to validated public IPs, and applies a 60-request per-minute process-local burst limit.

Built by **Bubacarr Minteh** (Data Science & Machine Learning).

## Run Locally

Use Python 3.12. Install the application and test dependencies, then start the service:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
uvicorn main:app --reload
```

The interactive API documentation is at `/docs`. With no keys configured, local development is open. Never deploy an unprotected instance; the Render blueprint generates an `API_KEY` by default.

## API

`GET /healthz` is a lightweight Render health check. It does not require authentication.

`GET /metrics` exposes Prometheus request counts, error counts, and latency histograms. When `API_KEY` or `RAPIDAPI_PROXY_SECRET` is configured, metrics require the same authentication as scrape. `X-Request-ID` is returned on every response; valid caller-provided IDs are preserved, otherwise the API generates one.

`GET /api/v1/scrape/text?url=https%3A%2F%2Fexample.com` returns the requested URL and extracted text. Direct callers must send `X-API-Key` when `API_KEY` is configured. The endpoint supports public HTTP/HTTPS destinations only. It does not execute JavaScript or bypass access controls.

Expected errors use a structured `detail` object with `code` and `message`. Common status codes are 400 for invalid URLs, 401 for invalid credentials, 413 for pages above 1 MiB, 415 for non-HTML content, 429 for the local burst guard, 502 for target HTTP/connection failures, and 504 for target timeouts.

### Service Limits

- Request timeout: 10 seconds per connection attempt.
- Redirects: at most 5, with URL and DNS validation repeated for every destination.
- HTML body: at most 1 MiB, read in chunks no larger than 4 KiB.
- Text response: at most 6,000 characters.
- Local abuse guard: 60 requests per client identity per 60 seconds, in process memory only.
- Paid subscription quotas and billing: configured and enforced by RapidAPI, not by this service.

## Deploy To Render

1. Create a GitHub repository whose **root is this folder** (`Bintu API` contents: `main.py`, `render.yaml`, `bintu_api/`, `.github/`). Do not push the parent `Web Scraping & Data Extraction API` folder as the repo root, or Render/CI will not find the blueprint and workflows.
2. In Render, create a new Blueprint and select that repository. Render reads `render.yaml`, installs `requirements.txt`, and starts Uvicorn on the assigned port.
3. Wait for `/healthz` to pass. Copy the generated `API_KEY` from the service environment for direct API access. Do not commit either secret.
4. Test the deployed `/docs` page and make an authenticated scrape request before publishing (or run `smoke_check.py`).

The free instance can sleep while idle, so the first request may be slow. Free services are best for validation and early users, not latency-sensitive production or an uptime guarantee. The local burst guard resets on restarts and is not shared across instances. It is not a paid quota; use RapidAPI plan limits as the billing authority.

GitHub Actions runs the offline test suite for pushes and pull requests. Render is configured to deploy linked commits only after CI checks pass.

## RapidAPI Publishing

RapidAPI handles subscriber authentication and billing at its gateway. Use this checklist when listing:

1. Deploy the Render service and confirm `/healthz` and `smoke_check.py` pass.
2. In the RapidAPI provider dashboard, set the API base URL to your Render root (no trailing path).
3. Copy RapidAPI's provider proxy secret into Render as `RAPIDAPI_PROXY_SECRET` (keep `API_KEY` for owner/direct access).
4. Define at least one free trial plan and one paid plan with monthly request quotas in RapidAPI.
5. Publish the single endpoint `GET /api/v1/scrape/text` with required query param `url`.
6. Add the consumer examples below to the listing; never put `API_KEY` or `RAPIDAPI_PROXY_SECRET` in public examples.

Subscriber call through RapidAPI (headers RapidAPI injects for you in their playground):

```bash
curl --request GET \
  --url "https://YOUR_RAPIDAPI_HOST/api/v1/scrape/text?url=https%3A%2F%2Fexample.com" \
  --header "x-rapidapi-host: YOUR_RAPIDAPI_HOST" \
  --header "x-rapidapi-key: YOUR_RAPIDAPI_USER_KEY"
```

Direct owner call against Render (not for public listing examples):

```bash
curl --request GET \
  --url "https://your-service.onrender.com/api/v1/scrape/text?url=https%3A%2F%2Fexample.com" \
  --header "X-API-Key: YOUR_RENDER_API_KEY"
```

Requests authenticated with `X-RapidAPI-Proxy-Secret` are accepted; their `X-RapidAPI-User` identity receives an independent 60-request-per-minute bucket. Keep `API_KEY` for owner/direct access, and never expose either secret in client examples.

Configure subscription plans, monthly quotas, and pricing in RapidAPI. Start with a small free trial and paid tiers based on measured Render latency, failure rates, and upstream costs. The service's 60-per-minute guard is a burst limit, not a monthly quota or billing system. Marketplace placement and revenue are not guaranteed.

Only scrape content you are authorized to access. Respect the target site's terms and robots policy. This API does not circumvent logins, CAPTCHAs, paywalls, or anti-bot controls.

## Tests

The regression suite uses mocked upstream responses and makes no live network requests:

```powershell
python -m unittest discover -s . -p "test_*.py" -v
```

After Render is live, run a real-network smoke check (stdlib only; no extra packages):

```powershell
$env:BINTU_BASE_URL = "https://your-service.onrender.com"
$env:BINTU_API_KEY = "your-api-key"
python smoke_check.py
```

The smoke script hits `/healthz`, then scrapes `https://example.com/` through `/api/v1/scrape/text`. Override the target with `BINTU_SMOKE_TARGET_URL` if needed. Expect a slow first run on the free Render plan while the instance wakes up.