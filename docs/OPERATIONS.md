# Operations runbook

This runbook covers routine deployment checks, monitoring, common incidents,
and credential rotation for the Bintu Data Extraction API.

## Service URLs

| Item | URL |
|---|---|
| Production base URL | https://bintu-api.onrender.com |
| Health check | https://bintu-api.onrender.com/healthz |
| Version | https://bintu-api.onrender.com/version |
| OpenAPI documentation | https://bintu-api.onrender.com/docs |
| Metrics | https://bintu-api.onrender.com/metrics |

## Release checklist

1. Run the full test suite:

   ```powershell
   python -m pytest tests -q
   ```

2. Confirm the working tree is clean:

   ```powershell
   git status
   ```

3. Push the release commit and tag:

   ```powershell
   git push
   git tag -a v1.2.1 -m "Release 1.2.1"
   git push origin v1.2.1
   ```

4. Wait for Render to deploy.

5. Run the live smoke test:

   ```powershell
   .\scripts\smoke_test.ps1
   ```

6. Confirm the deployed version:

   ```powershell
   Invoke-RestMethod -Uri "https://bintu-api.onrender.com/version"
   ```

## Routine monitoring

Check these signals after every deployment:

- `/healthz` returns `"status": "ok"`.
- `/version` reports the expected release version.
- The smoke test completes with `Smoke test passed.`
- Render logs contain no repeated `auth_misconfiguration`, `redisratelimiterunavailable`,
  `supabasecacheupsertfailed`, or `internal_error` events.
- `/metrics` shows request, error, latency, and cache activity.

## Common incidents

### Health check fails

1. Open the Render dashboard and inspect the latest deploy logs.
2. Check whether required environment variables are present.
3. If `REQUIRE_AUTH=true`, ensure at least one valid credential is configured:
   `API_KEY` or `RAPIDAPI_PROXY_SECRET`.
4. Roll back to the previous Render deployment if the failure began immediately
   after a deploy.
5. Re-run the smoke test after recovery.

### REST requests return 401

1. Confirm the caller is sending `X-API-Key`.
2. Confirm the key is the master REST `API_KEY`; the scoped `MCP_API_KEY`
   does not unlock REST routes.
3. Check for copied whitespace, quotes, or an old rotated key.
4. Test with:

   ```powershell
   Invoke-RestMethod `
     -Uri "https://bintu-api.onrender.com/version" `
     -Headers @{ "X-API-Key" = $env:BINTU_API_KEY.Trim() }
   ```

### MCP calls return 401

1. Confirm the caller sends `X-API-Key` or `Authorization: Bearer`.
2. Accept either the scoped `MCP_API_KEY` or master `API_KEY` for MCP execution.
3. Remember that MCP discovery methods—`initialize`, `tools/list`, and `ping`—
   do not require credentials.

### Target pages fail with 4xx or 5xx

Treat upstream failures as target-site issues unless they began immediately after
a Bintu deployment:

- `400 invalid_or_unsafe_url`: use a public HTTP or HTTPS URL.
- `413 payload_too_large`: the target exceeds the 1 MiB limit.
- `415 unsupported_media_type`: the target is not HTML or XHTML.
- `429 burst_rate_limit_exceeded`: wait for the period in `Retry-After`.
- `502`: the target refused access, failed, redirected too often, or used
  unsupported compression.
- `504 upstream_timeout`: the target was slow or unresponsive.

## Credential rotation

Rotate a credential immediately if it may have been exposed in a chat, ticket,
shell history, screenshot, or public repository.

1. Generate a replacement key in the Render dashboard.
2. Update the deployment environment variable.
3. Redeploy or restart the service.
4. Update trusted internal systems with the new key.
5. Remove the old key only after consumers have migrated.
6. Run the smoke test using the new key.

Never place credentials in URLs, client-side code, logs, commits, or support
tickets.

## Escalation

For a customer report, collect:

- The `X-Request-ID` response header
- HTTP status code
- Response `detail.code`
- Target URL, if the caller can share it safely
- Time of request
- Whether the issue is constant or intermittent

Do not ask for or store API keys, bearer tokens, or full page content.
