# Bintu Data Extraction API — RapidAPI + MCPize listing pack (paste into provider dashboards)

> Scope: this pack describes the existing scrape and MCP surfaces,
> not the REST reader as a new MCP tool. Pricing, quotas, marketplace
> configuration, and dated live observations require separate
> verification. Token counts are estimates, not exact model-tokenizer
> counts.

# Source of truth: README.md "Storefront parity" table + /docs. Error codes and limits must match the app.
# NEVER send MCPize buyers to RapidAPI (or vice versa): each gateway bills its own subscribers.

## Short description (Spotlight 1, keep)
Extract clean, readable text from public HTML pages with a simple API.

## Spotlight 2 (add: output shape)
Input:  GET /api/v1/scrape/text?url=https://www.iana.org/domains/reserved
Output: {"url": "https://www.iana.org/domains/reserved", "text": "# IANA-managed Reserved Domains\n## Example domains\n...", "truncated": false}
Headings, tables, and links preserved; nav/header/footer stripped unless requested.

## Long description (paste)
Bintu turns public web pages into clean, readable text for AI ingestion, monitoring, and readability. Token-Sanitized Context Gateway for AI agents: deterministic max_tokens chunks, tokens/cache_hit/tokens_saved_estimate on every MCP call.

What you get:
- Article/main content preferred; nav, header, footer, scripts, and boilerplate stripped by default
- Headings (#/##/###), tables (Markdown pipes), links as `label (absolute URL)`
- `truncated: true` when the 6,000-character cap applies; text cut at a word boundary
- JavaScript rendering is currently disabled (`render_js=true` returns 400 `render_js_disabled`); plain-HTML extraction only
- MCP: standard Streamable HTTP endpoint at `POST /mcp` for Claude connectors and Claude Code; legacy helpers at `GET /mcp/tools` and `POST /mcp/tools/call`; `mode=chunk` (alias `chunked`), `max_tokens` (alias `chunk_token_budget`); every mode returns the unified JSON envelope `{mode, tokens, chunk_count, cache_hit, source_url, extracted_at, tokens_saved_estimate, truncated, chunks}` in `content[0].text` plus `X-Token-Usage` header; no tier caps in code (dashboards own quota)

What Bintu refuses (by design, no exceptions):
- Logins, paywalls, CAPTCHAs, or anti-bot bypasses
- Non-HTML content (PDFs, images, video, JSON)
- Private/non-public URLs (SSRF-guarded: DNS revalidated per redirect hop, private IPs rejected, 1 MiB cap)

Limits:
| Guardrail | Value |
|---|---|
| Upstream body | 1 MiB max (raw + decompressed) |
| Content types | `text/html`, `application/xhtml+xml` only |
| Text response | 6,000 chars max, `truncated` flag |
| Redirects | 5 max, revalidated per hop |
| Burst guard | 60 req / 60 s per identity (RapidAPI user or IP) |
| Local cache | 5 min per instance; 24 h persistent cache when configured |
| Monthly quota | Enforced by RapidAPI plan, not by this service |

Errors (JSON `detail.code`):
| HTTP | Code | Meaning |
|---|---|---|
| 400 | invalid_or_unsafe_url | Bad or non-public URL |
| 400 | render_js_disabled | `render_js=true` while JS rendering is disabled; retry with `render_js=false` |
| 401 | invalid_api_key | Missing/invalid credential |
| 413 | payload_too_large | Page exceeds 1 MiB |
| 415 | unsupported_media_type | Not HTML/XHTML |
| 429 | burst_rate_limit_exceeded | Over 60/60s burst (`Retry-After` header) |
| 502 | upstream_http_error / upstream_connection_error / too_many_redirects / unsupported_content_encoding | Target failed |
| 504 | upstream_timeout | Target too slow |

Snippets:
```bash
curl.exe --get "https://bintu-data-extraction-api.p.rapidapi.com/api/v1/scrape/text" \
  --data-urlencode "url=https://www.iana.org/domains/reserved" \
  --header "X-RapidAPI-Key: $YOUR_KEY" \
  --header "X-RapidAPI-Host: bintu-data-extraction-api.p.rapidapi.com"
```
```python
import urllib.parse, urllib.request, json
params = urllib.parse.urlencode({"url": "https://www.iana.org/domains/reserved"})
req = urllib.request.Request(
    f"https://bintu-data-extraction-api.p.rapidapi.com/api/v1/scrape/text?{params}",
    headers={"X-RapidAPI-Key": "YOUR_KEY", "X-RapidAPI-Host": "bintu-data-extraction-api.p.rapidapi.com"},
)
print(json.load(urllib.request.urlopen(req, timeout=30))["text"][:500])
```
```javascript
const params = new URLSearchParams({ url: "https://www.iana.org/domains/reserved" });
const res = await fetch(`https://bintu-data-extraction-api.p.rapidapi.com/api/v1/scrape/text?${params}`, {
  headers: { "X-RapidAPI-Key": "YOUR_KEY", "X-RapidAPI-Host": "bintu-data-extraction-api.p.rapidapi.com" },
});
console.log((await res.json()).text.slice(0, 500));
```

Plans (monthly quota enforced by RapidAPI; burst guard always 60/60s; plain HTML only while rendering is disabled):
- BASIC $0: 100 req/mo — trial only
- PRO $9: 10,000 req/mo — matches current subscriber
- ULTRA $29: 50,000 req/mo
- MEGA $79: 100,000+ req/mo, contact seller for custom
JS rendering (`render_js=true`) currently returns 400 `render_js_disabled` on all plans; quotas above are plain-HTML. Rendering must remain disabled until the security prerequisites in root SECURITY.md are satisfied.
Support: include the `X-Request-ID` response header (see FEEDBACK.md template).
Docs: https://bintu-api.onrender.com/docs — Health: https://bintu-api.onrender.com/healthz

## MCPize listing pack (paste into MCPize dashboard — Description / Quick Start / Monetize)

Gateway: `https://bintu-web-reader.mcpize.run` (upstream `POST https://bintu-api.onrender.com/mcp`).
Verified live 2026-10-17: discovery lists `bintu_scrape_text`; `tools/call`
`{"url": "https://www.iana.org/domains/reserved", "render_js": false}` →
`{"content": [{"type": "text", "text": "# IANA-managed Reserved Domains\n..."}], "isError": false}`.
Cold fetch ~2–6 s, Supabase 24 h cache hit ~300 ms.
OAuth path verified live 2026-10-18: Claude Web connector "Sign in now"
(CIMD) → MCPize consent screen → token → live scrapes in chat.

Card / Short description (the form's "few plain words" card field — keep it one or two sentences):

```markdown
Web scraper MCP server for Claude, Cursor, and LLM agents. Returns readable Markdown from supported public HTML pages. Powered by Bintu.
```

GitHub field: `https://github.com/l20941485-blip/Bintu-API` (fills the audit's Trust signal; leave Website empty unless you have a real site — never `example.com`).

Description (paste; do NOT mention RapidAPI — MCPize bills its own subscribers):

```markdown
Token-Sanitized Context Gateway for AI agents. Strips tracking scripts, footers, and HTML noise with deterministic max_tokens chunks — predictable context budgets, not raw dumps. Perfect for Claude Code and Cursor agents. Powered by Bintu.

Subscribe on this page, copy your MCPize API key (sk_…). No upstream Bintu key needed — the gateway injects your credential; billing, rate limits, and analytics are handled here.

What you get:
- Article/main content preferred; nav, header, footer, scripts stripped by default
- Headings (#/##/###), tables (Markdown pipes), links as label (absolute URL)
- 6,000-character cap with word-boundary cut; truncated flag when it applies
- Plain-HTML extraction; render_js=true returns a retry-with-false hint (JS rendering disabled)
- Token Tax engine: mode=chunk (alias chunked), max_tokens (alias chunk_token_budget); every mode returns the unified JSON envelope {mode, tokens, chunk_count, cache_hit, source_url, extracted_at, tokens_saved_estimate, truncated, chunks} plus X-Token-Usage header; 401 -32001 carries upgrade_url; no tier caps in code (dashboards own quota)

What it refuses (by design, no exceptions):
- Logins, paywalls, CAPTCHAs, anti-bot bypasses
- Non-HTML content (PDFs, images, video, JSON)
- Private/non-public URLs (SSRF-guarded, 1 MiB cap, 5 redirects max)

Limits: the upstream service applies a burst guard; callers sharing an upstream credential may share its bucket. Subscriber plan quotas are managed by MCPize.
Docs & examples: https://github.com/l20941485-blip/Bintu-API
```

Quick Start (paste):

```markdown
1. Click Subscribe and pick a tier below.
2. Copy your MCPize API key (sk_...).
3. Connect your client:

Claude Code:
claude mcp add --transport http bintu https://bintu-web-reader.mcpize.run --header "Authorization: Bearer YOUR_MCPIZE_KEY"

Claude web/Desktop: add a custom connector with URL https://bintu-web-reader.mcpize.run and choose "Sign in now" — sign in with your MCPize account and approve access once. (If your plan shows a request-header option, the sk_… key works there too.)

4. Call the tool:

Tool: bintu_scrape_text
Arguments: {"url": "https://www.iana.org/domains/reserved", "render_js": false, "mode": "scrape"}

Budgeted RAG variant: {"url": "https://www.iana.org/domains/reserved", "mode": "chunked", "chunk_token_budget": 500} (aliases for mode=chunk, max_tokens=500).

5. Expect (unified envelope in content[0].text):

{"content": [{"type": "text", "text": "{\"mode\": \"scrape\", \"tokens\": 42, \"chunk_count\": 1, \"cache_hit\": false, \"source_url\": \"...\", \"extracted_at\": \"...\", \"tokens_saved_estimate\": 0, \"truncated\": false, \"chunks\": [{\"index\": 0, \"text\": \"# IANA-managed Reserved Domains...\", \"tokens\": 42}]}"}], "isError": false}

Response header X-Token-Usage: tokens=42, chunks=1, cache_hit=0.

If isError is true, read the text — it tells the model how to self-correct (e.g. bad URL, rate limit, render_js_disabled → retry with false).
```

Publisher tiers (dashboard → Monetize; mirror RapidAPI so storefronts don't undercut each other; 80% via Stripe Connect, $100 minimum payout):
- Free $0: ~1,000 calls/mo — discovery
- Pro $9: ~10,000 calls/mo — solo devs, Claude Code daily use
- Ultra $29: ~50,000 calls/mo — agents, RAG pipelines, monitoring
- Mega $79: ~200,000 calls/mo — teams, high-volume ingestion

Tags: scraper, claude, web-scraping + readability, rag, markdown, extraction (if slots allow).

Upstream notes (operator only, NOT for the listing): Base URL `https://bintu-api.onrender.com/mcp`;
upstream auth = single `X-API-Key` (Render `API_KEY`).
`initialize`, `tools/list`, and `ping` are public discovery methods.
`tools/call` requires authentication; `GET /sse` + `GET /mcp/sse` aliases cover the SSE probe; keep the
MCPize gateway URL on the cron keep-alive next to Render `/healthz`.

## Endpoint tests (add in RapidAPI dashboard, all against https://example.com/, render_js=false)
1. Happy path: GET /api/v1/scrape/text?url=https://example.com/ -> 200, body has `url`, non-empty `text`, boolean `truncated`
2. Bad URL: ?url=nota-url -> 400 `invalid_or_unsafe_url`
3. No key: no headers -> 401 `invalid_api_key`
4. Non-HTML: ?url=https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf -> 415 `unsupported_media_type`
5. Burst: 61 rapid calls -> 429 `burst_rate_limit_exceeded` + `Retry-After` header
6. Render disabled: GET /api/v1/scrape/text?url=https://example.com/&render_js=true -> 400 `render_js_disabled`

## Tags
web scraping, html to text, article extractor, readability api, rag ingestion, mcp tool

## render_js policy (decided 2026-10-14: soft-disabled, NOT paid-only)
RapidAPI does not send plan tier in headers (`X-RapidAPI-User` only), so per-plan
gating is unenforceable. `render_js=true` returns 400 `render_js_disabled` on all
entry points (REST, mobile, MCP) while rendering is disabled.
Do not re-enable rendering until the security prerequisites in root SECURITY.md are satisfied. Paid infrastructure alone does not resolve the documented rendering risk.
