# Contributing

## Set up locally

From the repository root:

```powershell
python -m venv .venv1
.\.venv1\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
```

Copy the environment template and add local values as needed:

```powershell
Copy-Item .env.example .env
```

Do not commit `.env`, API keys, proxy secrets, or Supabase credentials.

## Run the test suite

```powershell
python -m pytest tests -q
```

A healthy result looks like:

```text
828 passed, 1 warning, 376 subtests passed
```

Warnings from `starlette.testclient` are currently expected and do not fail the suite.

## Run a live smoke test

The smoke test performs one real health check, authenticated REST scrape, and MCP discovery request:

```powershell
$env:BINTU_API_KEY = Read-Host "Paste REST API key"
.\scripts\smoke_test.ps1
```

It should finish with:

```text
Smoke test passed.
```

## Try the examples

```powershell
$env:BINTU_BASE_URL = "[https://bintu-api.onrender.com](https://bintu-api.onrender.com)"
$env:BINTU_API_KEY = Read-Host "Paste REST API key"

python .\examples\rest_python.py [https://example.com](https://example.com)
node .\examples\rest_javascript.js [https://example.com](https://example.com)
python .\examples\mcp_python.py [https://example.com](https://example.com)
```

## Before pushing

1. Run `python -m pytest tests -q`.
2. Confirm `git status` shows only intended changes.
3. Use a short, imperative commit message.
4. Push to `main` only after the suite is green.

```powershell
git add <files>
git commit -m "Describe the change"
git push
git status
```

## Code expectations

- Keep user-facing errors structured with `code`, `message`, and, where useful, `hint`.
- Never log or return API keys, caller credentials, raw target URLs for rejected requests, or extracted page content.
- Preserve the REST/MCP response contract: `approx_tokens`, `truncated`, `limiting_factor`, `cache_hit`, and `cache_layer`.
- Add or update tests when changing extraction, authentication, rate limiting, caching, MCP, or error behavior.
