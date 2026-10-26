# Bintu API Deployment Runbook

This runbook covers deploying, validating, monitoring, and recovering the Bintu API service.

## 1. Deployment source

The deployment branch is:

```text
main
```

Before deploying, ensure the working tree is clean and the latest commit is pushed:

```powershell
cd C:\Users\Bubacarr\Documents\Bintu-API
git status
git pull origin main
git log --oneline -5
```

Expected:

```text
nothing to commit, working tree clean
```

## 2. Required environment variables

Configure these in the Render dashboard under **Environment**. Never commit secrets to Git.

| Variable | Required | Purpose |
|---|---:|---|
| `API_KEY` | Yes for production | Master API key for direct API and MCP access. |
| `RAPIDAPI_PROXY_SECRET` | Optional | Enables RapidAPI subscriber identity and metering. |
| `SUPABASE_URL` | Optional | Enables persistent cache and usage persistence. |
| `SUPABASE_SERVICE_KEY` | Optional | Service credential for Supabase access. |
| `RENDER_JS_ENABLED` | Optional | Set to `true` to enable JavaScript rendering. |
| `CONTACT_EMAIL` | Recommended | Contact address included in the honest User-Agent. |
| `BOT_INFO_URL` | Recommended | Public bot information URL included in the User-Agent. |

Do not place raw API keys in URLs, logs, commits, or client-side code.

## 3. Deploy to Render

1. Open the Render dashboard.
2. Select the Bintu API service.
3. Confirm the connected repository and branch are `main`.
4. Select **Manual Deploy** → **Deploy latest commit**.
5. Wait for the build and deploy to complete.
6. Confirm the deployment shows the intended commit SHA, for example:

```text
8b180e6 feat: enforce MCP rate limits and improve URL sanitization
```

## 4. Run the deployment smoke check

From the local repository:

```powershell
cd C:\Users\Bubacarr\Documents\Bintu-API
$env:BINTU_BASE_URL = "[https://bintu-api.onrender.com](https://bintu-api.onrender.com)"
$env:BINTU_API_KEY = "your-production-key"
python smoke_check.py
```

Expected output:

```text
Checking health at [https://bintu-api.onrender.com/healthz](https://bintu-api.onrender.com/healthz) ...
OK  /healthz
Checking scrape against [https://example.com/](https://example.com/) ...
OK  /api/v1/scrape/text
Checking unsafe URL rejection for http://127.0.0.1/ ...
OK  unsafe URL rejected with invalid_or_unsafe_url
Smoke check passed.
```

If the smoke check fails, do not send production traffic to the new deployment. Follow the rollback procedure below.

## 5. Post-deploy validation

Run the full local test suite before promoting changes:

```powershell
python -m pytest tests -q
```

Expected:

```text
367 passed
```

Then verify these live behaviors:

- `/healthz` returns HTTP 200.
- A public HTTPS URL returns HTTP 200 with non-empty extracted text.
- `http://127.0.0.1/` returns HTTP 400 with `invalid_or_unsafe_url`.
- Repeated requests to the same URL can return a cache hit.
- Rate-limited callers receive HTTP 429 and a `Retry-After` header.

## 6. Monitoring

Watch these signals in Render logs and your observability dashboard.

| Signal | Healthy behavior | Investigate when |
|---|---|---|
| `/healthz` | HTTP 200, `status: ok` | Non-200 or repeated failures |
| Extraction success | HTTP 200 with non-empty text | Rising 5xx or empty responses |
| `invalid_or_unsafe_url` | Present for malicious or private targets | Sudden large increase may indicate scanning |
| `blocked_by_robots` | Expected for disallowed targets | Sudden increase may indicate upstream policy changes |
| `robots_unreachable` | Rare | Persistent increase suggests DNS/network issues |
| `upstream_error` | Low and transient | Persistent increase suggests target or network issues |
| Cache hits | Increase for repeated public URLs | Zero hits may indicate cache misconfiguration |
| Rate-limit events | Present under load | Unexpected 429s from legitimate callers |
| Request duration | Stable for comparable URLs | Sharp increase may indicate upstream or rendering issues |

## 7. Rollback procedure

If a deployment fails smoke testing or causes production errors:

1. Open the Render dashboard.
2. Select **Deploys**.
3. Find the last known-good deployment.
4. Select **Rollback**.
5. Wait for the rollback to become live.
6. Run the smoke check again:

```powershell
$env:BINTU_BASE_URL = "[https://bintu-api.onrender.com](https://bintu-api.onrender.com)"
$env:BINTU_API_KEY = "your-production-key"
python smoke_check.py
```

7. Create a Git issue describing:
   - The failing commit SHA.
   - The smoke-check or production symptom.
   - Relevant request IDs.
   - The rollback commit SHA.

Do not push a new fix directly to `main` until the failure is understood.

## 8. Incident response

### API returns 5xx

1. Check Render logs for the affected `request_id`.
2. Identify the `error_type` and target URL hash.
3. Determine whether the issue is limited to one upstream domain or all requests.
4. If widespread, roll back to the last known-good deployment.
5. Re-run the smoke check after rollback.

### Unsafe URL rejection stops working

1. Run:

```powershell
python smoke_check.py
```

2. Confirm the unsafe check returns `400 invalid_or_unsafe_url`.
3. If it does not, roll back immediately.
4. Investigate the latest changes to `bintu_api/scraper.py` and `bintu_api/routes.py`.

### Rate limits are not enforced

1. Run the full suite:

```powershell
python -m pytest tests/test_rate_limit_contract.py -q
```

2. Confirm all three surfaces return HTTP 429 when the limiter trips.
3. Inspect recent changes to `bintu_api/mcp.py`, `bintu_api/mcp_streamable.py`, and `bintu_api/routes.py`.
4. Roll back if enforcement is missing in production.

### Credentials may have leaked

1. Rotate `API_KEY` immediately in Render.
2. Rotate `SUPABASE_SERVICE_KEY` if applicable.
3. Review Git history and logs for exposed values.
4. Invalidate or replace any compromised customer credentials.
5. Document the incident and corrective actions.

## 9. Release checklist

Before marking a release complete:

- [ ] `git status` is clean.
- [ ] Latest commit is pushed to `origin/main`.
- [ ] Full test suite passes.
- [ ] Render deployment uses the intended commit SHA.
- [ ] `/healthz` returns HTTP 200.
- [ ] Production smoke check passes.
- [ ] Unsafe URL rejection returns `400 invalid_or_unsafe_url`.
- [ ] Logs contain no raw API keys, target URLs for rejected requests, or caller credentials.
- [ ] Monitoring dashboards are receiving request and extraction events.