# Bintu Data Extraction API — RapidAPI listing pack (paste into provider dashboard)
# Source of truth: README.md + /docs. Error codes and limits must match the app.

## Short description (Spotlight 1, keep)
Extract clean, readable text from public HTML pages with a simple API.

## Spotlight 2 (add: output shape)
Input:  GET /api/v1/scrape/text?url=https://www.iana.org/domains/reserved
Output: {"url": "https://www.iana.org/domains/reserved", "text": "# IANA-managed Reserved Domains\n## Example domains\n...", "truncated": false}
Headings, tables, and links preserved; nav/header/footer stripped unless requested.

## Long description (paste)
Bintu turns public web pages into clean, readable text for AI ingestion, monitoring, and readability.

What you get:
- Article/main content preferred; nav, header, footer, scripts, and boilerplate stripped by default
- Headings (#/##/###), tables (Markdown pipes), links as `label (absolute URL)`
- `truncated: true` when the 6,000-character cap applies; text cut at a word boundary
- JavaScript rendering is currently disabled (`render_js=true` returns 400 `render_js_disabled`); plain-HTML extraction only
- MCP: standard Streamable HTTP endpoint at `POST /mcp` for Claude connectors and Claude Code; legacy helpers at `GET /mcp/tools` and `POST /mcp/tools/call`

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
JS rendering (`render_js=true`) currently returns 400 `render_js_disabled` on all plans; quotas above are plain-HTML. Rendering returns only if re-enabled via `RENDER_JS_ENABLED=true` on paid infra.
Support: include the `X-Request-ID` response header (see FEEDBACK.md template).
Docs: https://bintu-api.onrender.com/docs — Health: https://bintu-api.onrender.com/healthz

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
entry points (REST, mobile, MCP) until `RENDER_JS_ENABLED=true` is set on paid infra.
Re-enable = one env var, no code deploy. Update plans copy when that happens.
