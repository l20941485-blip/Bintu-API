# Bintu Data Extraction API — Feedback & Validation Log

Working document for reporting problems, tracking deployment readiness, and
recording what has actually been verified against a running instance. Update it
in the same pull request as the change it describes; the README stays the
reference for behaviour, this file stays the record of what we observed.

- Service: `bintu-data-extraction-api` (FastAPI, Render free tier, RapidAPI storefront)
- Contract: `GET /healthz`, `GET /version`, `GET /metrics`, `GET /api/v1/scrape/text?url=...`
- Guardrails under test: 1 MiB upstream body cap, HTML/XHTML content-type only,
  public-HTTP(S) destinations with DNS revalidation per redirect, 60 req / 60 s
  burst guard per identity, 6,000-character text cap, 5-minute cache.

## How to file something

Open an issue (or a row in the table below for quick triage) with the fields from
[Feedback Template](#feedback-template). Always include the `X-Request-ID`
response header: it is echoed on every response and is what correlates a caller's
complaint with the `bintu_api.request` log line and `/metrics` counters.

## Current status

| Area | State | Evidence |
|---|---|---|
| Offline unit suite | 39 passing | `python -m unittest discover -s tests -t . -p "test_*.py" -v` |
| `tests/test_integration.py` | 2 pre-existing errors on this workstation | `TimeoutError` connecting to `127.0.0.1`; loopback traffic blocked locally, unrelated to app code |
| Dependency drift | Resolved | `redis==5.0.0` was pinned but absent from `.venv`; reinstalled so `REDIS_URL` deployments and editor resolution agree with `requirements.txt` |
| Type checking | `redis` import resolves | `import redis` is soft by design; see `bintu_api/rate_limit.py` |
| Live deploy | Not verified | Needs `BINTU_BASE_URL` + `python smoke_check.py` |

## Environment checklist

`.env.example` is the committed template; `.env` is git-ignored and docker-ignored.

| Variable | Read by | Status / note |
|---|---|---|
| `API_KEY` | `Settings.from_env` | Generated locally; matches `generateValue: true` in `render.yaml`, so Render holds its own independent value |
| `RAPIDAPI_PROXY_SECRET` | `Settings.from_env` | `sync: false` in `render.yaml` — set it in the Render dashboard **and** the RapidAPI provider dashboard, or RapidAPI traffic is rejected with 401 |
| `CACHE_TTL_SECONDS` | `Settings.from_env` | Out-of-range values degrade to 300 with a warning instead of failing startup |
| `REDIS_URL` | `Settings.from_env` | Empty = process-local burst guard; each instance then enforces its own window |
| `BINTU_BASE_URL`, `BINTU_API_KEY`, `BINTU_SMOKE_TARGET_URL` | `smoke_check.py` | Post-deploy only |
| `BINTU_RAPIDAPI_KEY` | tests/scripts only | RapidAPI **consumer** key for `X-RapidAPI-Key`; not an app secret |
| `RENDER_API_KEY` | Render API/CLI only | Account-level credential; never reuse as `API_KEY` |

Anything shown above as "not read by the application" is intentionally named
differently from the app's secrets so a third-party credential cannot be loaded
into `Settings` by accident. Rotate any credential that has been pasted into a
chat, ticket, or shell history rather than assuming a file mode protects it.

## Verification commands

```powershell
Copy-Item .env.example .env    # then edit
# export the pairs (see header of .env.example), then:
uvicorn main:app --reload

curl.exe -s http://127.0.0.1:8000/healthz
curl.exe -s -H "X-API-Key: $env:API_KEY" http://127.0.0.1:8000/version
curl.exe -s -H "X-API-Key: $env:API_KEY" "http://127.0.0.1:8000/api/v1/scrape/text?url=https://example.com/"

python smoke_check.py          # against the deployed URL, not localhost
```

Expected outcomes, per `README.md`: 400 invalid URL, 401 missing or wrong
credentials, 413 upstream above 1 MiB, 415 non-HTML, 429 burst limit with
`Retry-After`, 502 upstream/connection failure, 504 upstream timeout.

## Known issues & findings

| ID | Date | Severity | Area | Finding | Status |
|---|---|---|---|---|---|
| F-001 | 2026-09-30 | Low | Dev env | `redis==5.0.0` pinned in `requirements.txt` but missing from `.venv`, so `REDIS_URL` silently fell back to the in-process guard and the editor could not resolve the import. Now installed; factory logs `redis_url_configured_but_package_unavailable` on that downgrade | Closed |
| F-002 | 2026-09-30 | Low | Tests | `tests/test_integration.py` loopback cases time out on this workstation (Windows blocks the in-test HTTP listener). CI on Linux is unaffected; the two tests exercise `fetch_html` socketing only | Open, environment-specific |
| F-003 | 2026-09-30 | Medium | Deployment | Free-tier instance sleeps when idle, so first request after inactivity can exceed RapidAPI's upstream timeout; burst buckets also reset on restart and are per-instance unless `REDIS_URL` is set | Open, accepted for free tier |
| F-004 | 2026-09-30 | Medium | Quota | The 60/60s guard is a burst limit, not a monthly quota. Paid plan limits and billing are enforced by RapidAPI, so a plan misconfiguration shows up as billable traffic rather than a 429 here | Open, RapidAPI-owned |

Severity: **Critical** data loss, credential exposure, or SSRF/auth bypass;
**High** wrong results or an endpoint down for real traffic; **Medium** degraded
behaviour with a workaround; **Low** cosmetic, tooling, or docs.

Anything Critical or High, or any report touching the SSRF guards, redirect
revalidation, 1 MiB cap, or authentication, is fixed before any other work.

## Feedback Template

```text
Date:            YYYY-MM-DD
Reporter:        (name, RapidAPI user/team, or "internal")
Endpoint:        GET /api/v1/scrape/text
Request URL:     url=... (and include_nav/header/footer if used)
Transport:       direct Render URL | RapidAPI storefront
X-Request-ID:    (from the response header)
Status:          400 | 401 | 413 | 415 | 429 | 502 | 504 | other
Expected:
Actual:          (JSON detail.code / detail.message, or extracted text sample)
Frequency:       always | intermittent (N of M calls)
Severity:        Critical | High | Medium | Low
Notes:           target site robots/terms, page size, whether JS rendering is needed
```

Extraction-quality reports ("missing article body", "nav included") need the
target URL plus a text excerpt: the parser is intentionally conservative, does
not execute JavaScript, and strips `nav`/`header`/`footer` unless the caller sets
`include_nav` / `include_header` / `include_footer`. Requests to bypass a login,
paywall, CAPTCHA, or anti-bot control are declined, not deferred.

## Release gate

1. Offline suite green: `python -m unittest discover -s tests -t . -p "test_*.py"` (CI runs
   this on push/PR; Render deploys linked commits only once checks pass).
2. `python smoke_check.py` green against the deployed instance.
3. `/version` reviewed to confirm no secret material is echoed.
4. New findings logged above with an ID and severity.

