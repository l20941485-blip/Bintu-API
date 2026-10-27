# Bintu API Deployment Runbook

This runbook covers release preparation, deployment validation, monitoring,
and recovery. Run repository commands from the repository root.

## 1. Prepare the release

Production deployments are intended to use `main`. Confirm the actual
repository and deployment branch in the Render dashboard before deploying.

Work on a feature branch and review changes through a pull request.
Do not run `git pull origin main` from an arbitrary feature branch as a
deployment preparation step.

Before merging:

```powershell
git status --short --branch
python -m pytest tests -q
git diff --check
```

Stop if tests or whitespace checks fail. Review the complete PR diff and
required CI checks. A local passing test run does not establish CI success
or production availability.

Record the intended merge commit SHA. Confirm that the deployment uses that
commit rather than relying on a hardcoded example SHA.

## 2. Environment configuration

Configure secrets in the deployment environment, never in committed files.

| Variable | Purpose |
|---|---|
| `API_KEY` | Master key for direct API access and supported MCP authentication. |
| `REQUIRE_AUTH` | Set to `true` in production to fail closed when authentication is misconfigured. |
| `RAPIDAPI_PROXY_SECRET` | Provider secret for verified RapidAPI traffic; match the provider dashboard configuration. |
| `MCP_API_KEY` | Optional scoped MCP credential; it does not grant REST reader access. |
| `SUPABASE_URL` | Supabase project URL for configured database/mobile features. |
| `SUPABASE_ANON_KEY` | Public/anon project key used by configured mobile authentication features. |
| `SUPABASE_SERVICE_ROLE_KEY` | Server-only credential for persistent cache and usage accounting. Never expose it to clients. |
| `REDIS_URL` | Optional shared rate-limit backend; separate from reader snapshot storage. |
| `RENDER_JS_ENABLED` | Keep `false`; paid infrastructure alone does not resolve the documented rendering security risk. |
| `ROBOTS_MODE` | Keep `enforce` for robots-policy enforcement. |
| `ROBOTS_CACHE_TTL_SECONDS` | Robots policy cache lifetime; default 3600 seconds. |
| `CONTACT_EMAIL` | Real operator contact for the crawler User-Agent. |
| `BOT_INFO_URL` | Real public crawler information URL. |

Use `.env.example` and `bintu_api/settings.py` for supported configuration.
Do not assume that copying `.env.example` automatically loads environment
variables into the running process.

See root `SECURITY.md` before changing rendering or outbound-network behavior.

## 3. Reader deployment constraints

Reader snapshots are stored in memory in each application instance.
They are not persisted in Supabase or shared through Redis.

Defaults:

- 200,000 extracted text characters per retained document.
- 600-second fixed snapshot lifetime; continuation does not extend it.
- Up to 16 retained documents and 256 continuation handles per store.
- Oldest-inserted eviction when capacity is exceeded.

Restart, deployment, rollback, expiry, or capacity eviction can invalidate
continuations. Separate workers and instances cannot resolve one another's
cursors. Before promising reliable multi-worker continuation, implement and
validate an explicit routing or shared-storage design.

A shared direct API key represents one reader owner, not separate users.
Use only the reader's supported authenticated identities.

## 4. Deploy the intended commit

1. Merge only after required review and CI checks pass.
2. Confirm the connected repository and production branch in Render.
3. Check the configured automatic deployment policy. If deploying manually,
   select the intended commit through the available dashboard controls.
4. Wait for the build and deployment to finish.
5. Verify the running deployment's commit SHA.
6. Perform the live checks below before marking the release verified.

Do not change deployment policy or enable JavaScript rendering merely to
complete a release.

## 5. Run the existing production smoke check

The existing smoke script validates its implemented checks; do not assume
it exercises the reader endpoints.

Use a secure prompt rather than typing the production key into a command:

```powershell
$env:BINTU_BASE_URL = "[https://bintu-api.onrender.com](https://bintu-api.onrender.com)"
$secure = Read-Host "Production API key" -AsSecureString
$env:BINTU_API_KEY = [System.Net.NetworkCredential]::new("", $secure).Password
Remove-Variable secure

python smoke_check.py

if ($LASTEXITCODE -ne 0) {
    throw "Production smoke check failed. Investigate before release sign-off."
}
```

Use a plain URL, not Markdown link syntax, in environment variables.

Alternatively, use the repository's manual live-smoke workflow only after
reviewing its inputs, secret handling, and target configuration.

## 6. Validate the deployed reader

Use the read-and-continue example in the README against the intended
deployment, with an authorized public HTML target long enough to require
continuation.

Confirm:

- Both reader routes appear in deployed OpenAPI.
- An unauthenticated reader request is rejected.
- An authenticated initial request returns non-empty text.
- A sufficiently long document returns `has_more=true` and a cursor.
- Continuation succeeds using the same authenticated owner.
- Continuation offsets meet the previous page's end offset.
- The final page returns `has_more=false` and `next_cursor=null`.
- Unknown cursors return `404 reader_snapshot_unavailable`.
- Responses contain `X-Request-ID`.

A short document that fits one page does not validate continuation.
Do not run burst-load tests against production as part of a routine smoke
check. Use controlled tests for rate limiting and caller isolation.

Record the tested commit, date, target, outcomes, and request IDs without
recording secrets, cursors, or sensitive extracted content.

## 7. Monitoring

Review HTTP request counts, errors, duration, and request-completion logs.
Use `X-Request-ID` to correlate reported failures.

Reader requests use the shared HTTP observability middleware. The reader
routes do not call the existing extraction-completion or extraction-failure
metric helpers; those metrics are not complete reader coverage.

Investigate:

- Widespread 5xx responses or increased request duration.
- Unexpected authentication failures or legitimate-caller rate limits.
- Increased `reader_snapshot_unavailable` responses, especially after
  deployment or in multi-worker configurations.
- Rate-limit backend fallback warnings.
- Unexpected raw credentials, target URLs, cursors, or document text in logs.

Expected expiry and eviction are distinct from upstream fetch failures.

## 8. Rollback and incidents

If deployment checks fail or production behavior regresses:

1. Identify the affected commit and request IDs.
2. Use the deployment platform's rollback controls to restore a known-good
   deployment.
3. Confirm the restored commit.
4. Rerun the applicable live checks.
5. Record the incident and corrective action.

Rollback or process restart invalidates process-local reader snapshots.
Clients may need to start a new read.

If unsafe-destination rejection regresses, treat it as a security incident
and stop exposure while investigating the fetch and redirect paths.

If credentials may have leaked, rotate the affected credentials, including
`API_KEY`, `MCP_API_KEY`, `RAPIDAPI_PROXY_SECRET`,
`SUPABASE_SERVICE_ROLE_KEY`, or `REDIS_URL` as applicable. Review repository
history and logs. Removing a visible copy does not revoke a credential.

Do not publish secrets or exploit details in public issues.

## 9. Release checklist

- [ ] Full local suite passes with `python -m pytest tests -q`.
- [ ] Complete PR diff reviewed and required CI checks pass.
- [ ] Intended production commit is identified.
- [ ] Deployment uses that commit.
- [ ] Production environment and reader worker topology reviewed.
- [ ] Existing production smoke check passes.
- [ ] Reader initial-read and continuation checks pass, if included in release.
- [ ] HTTP observability is present and its coverage limitations are understood.
- [ ] No secrets or sensitive content are exposed in validation records.
- [ ] Validation evidence is recorded separately from historical observations.
