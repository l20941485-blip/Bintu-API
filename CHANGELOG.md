# Changelog




All notable changes to the Bintu Data Extraction API will be documented here.




## [Unreleased]

### Added

- `bintu_rate_limiter_mode` Prometheus gauge reporting whether the active
  limiter is Redis-backed (`1`) or process-local fallback (`0`).
- Fallback-mode reporting when a configured Redis rate limiter fails and
  enters its existing 30-second fallback circuit.



- Authenticated REST document reader at `POST /api/v1/reader/read` and
  `POST /api/v1/reader/continue`.
- Caller-bound, opaque continuation handles for reading retained text
  snapshots without refetching the target.
- Reader page-text budgets with a default of 1,000 and a permitted range
  of 1 through 6,000 approximate tokens.
- A 200,000-character extracted-document retention limit; larger
  extractions are rejected rather than silently shortened.
- Bounded process-local retention: fixed 600-second snapshot lifetime,
  up to 16 documents and 256 continuation handles per application store.
  Capacity eviction can invalidate continuations before expiry.
- Reader route and real-application integration tests.
- Reader documentation covering authentication, continuation, retention,
  multi-worker limitations, and HTTP-level observability.

### Documentation

- Consolidated security guidance in root `SECURITY.md` and removed the
  duplicate `docs/SECURITY.md`.
- Clarified that paid infrastructure does not resolve the documented
  JavaScript-rendering DNS-rebinding risk.

## [1.2.0] — 2026-10-25




### Added




- Privacy-safe extraction observability for REST and MCP extraction paths.
- Structured `extraction_completed` telemetry with request ID, hashed target URL, extraction mode, cache status, token economics, truncation state, and limiting factor.
- Privacy-safe `extraction_failed` telemetry for MCP extraction failures.
- Failure metrics grouped by extraction mode, canonical failure code, and error type.
- Failure duration and upstream status telemetry without exposing target URLs or extracted content.
- Privacy-safe cache lookup telemetry with hit/miss outcome, cache layer, and persistent-cache age.
- Aggregate cache token-savings metrics by extraction mode and cache layer.
- Regression tests ensuring extraction and cache telemetry use hashed URLs and never expose raw target URLs or extracted content.
- Token-metering failure telemetry that records the error type without exposing API keys, target URLs, or extracted content.




### Changed




- Suppressed `httpx` and `httpcore` INFO request logs to prevent Supabase cache-query URLs—and therefore scraped target URLs—from appearing in Render logs.
- Extraction logs now identify targets by `url_hash` rather than the raw URL.
- `service_version` bumped from `"1.1.0"` to `"1.2.0"` in `bintu_api/settings.py`.




## [1.1.0] — 2026-10-22




### Response-shape changes




- `service_version` bumped from `"1.0.1"` to `"1.1.0"` in `bintu_api/settings.py`
- Added `approx_tokens: int` to `ScrapeTextResponse` — approximate token count computed as `ceil(characters / 4)` using a dependency-free whitespace-split tokenizer
- Added `token_method: str = "ceil(characters/4)"` — explicit tokenization method string
- Added deprecated `tokens: int` field — alias for `approx_tokens`, preserved for backward compatibility; documented as a **character-bound** alias, not a physical hardware tokenizer
- Added `tokens_saved_estimate: int` — estimated structural payload reduction: `max(0, approx_tokens(raw_html) - approx_tokens(extracted_text))`
- Added `effective_char_cap: int` with value `min(tier_threshold, max_tokens * 4)` — boundary precedence: char cap binds before token budget
- Added `truncated_split: bool` — `True` when content spans across multiple processing blocks (split), distinguished from `truncated` which means actual content loss
- Added `Provenance` nested model to all responses containing:
  - `request_id`: UUID4 string identifying the request
  - `fetched_at`: UTC ISO 8601 timestamp of when the fetch was initiated
  - `requested_url`: sanitized URL with all sensitive query strings fully stripped
  - `final_url`: fully resolved destination URL after following redirects
  - `upstream_status`, `redirect_count`, `content_type`, `bytes_fetched`, `content_sha256`
  - `cache`: CacheInfo hit/metadata
  - `extractor_version`: service version string
  - `removed`: RemovedStats instructional cleaning metrics (NOT security control validation)



### Phase E: Compliance Policy Ingestion




- C2: Dynamic User-Agent Assembly — format all outbound scraping request channels to register using an explicit, configurable compliance string: `BintuBot/<version> (+[BOT_INFO_URL]; [CONTACT_EMAIL])`. Never forge consumer browser signatures.
- C1: RFC 9309 Robots Rules Lifecycle — safely retrieve `/robots.txt` paths across target endpoints using hardened SSRF-safe client pooling; cache origin policy structures locally for exactly 1 hour; map HTTP 4xx error codes as explicit authorization to parse (allow), map 5xx errors or connection timeouts as total access restriction block (disallow); parse specific directives matching `User-agent: BintuBot` first before cascading down to global wildcards (`*`); ROBOTS_MODE runtime toggles configurable via environment strings matching `"enforce"` | `"warn"` | `"off"`; under enforce (the system default), immediately drop restricted actions with a `blocked_by_robots` exception payload; under warn, compile target data normally but append policy evaluation metrics into `provenance.robots` object.
- Clean Upstream Error Interception — capture target site status signals resulting in 401, 402, 403, or 429 responses; translate them instantly into a clean, structured `upstream_access_denied` error body configuration without executing automated retry chains, rotation mechanisms, or CAPTCHA handling routines.
- Compliance Assets Generation — authored comprehensive reference overview in `docs/bot.md` detailing crawler identities, structural signatures, contact mechanisms, and clear instructions for target site webmasters to issue blocking configurations via standard `robots.txt` paths.




### Backwards-incompatible / deprecations




- The `tokens` field is deprecated; new code should use `approx_tokens` instead. The `tokens` field will emit a deprecation warning in a future 2.x release.




### Tests




- Added assertions for non-zero `tokens_saved_estimate` on heavy pages
- Verified `truncated` vs `split` distinctions in response validation
- `token_method` — new field always present: `"whitespace"` (the tokenizer method used), no tiktoken dependency.
- `tokens` — deprecated alias for `approx_tokens`, kept one release so existing clients reading `tokens` do not break.
- `tokens_saved_estimate` — **redefined**. Now equals `approx_tokens (fetched HTML, best-effort decode) - approx_tokens (delivered text)`, the "fetched HTML tokens minus delivered text tokens" estimate. Previously clamped to 0 in scrape/chunk modes. Named and labelled as an *estimate*.
- `split` — new boolean: `true` when chunk mode delivered multiple chunks (content preserved, not lost). Distinguished from `truncated` which means actual content loss.
- `truncated` — now correctly threaded through MCP `scrape` mode (was hardcoded `False` in `context.py`, hiding the 6,000-char char cap being hit).
- `limiting_factor` — new field: `"char_cap"` when the 6,000-char cap bound the result, `"token_budget"` when summarize trimmed, `"none"` otherwise. Makes the precedence explicit: the char cap binds before `max_tokens`.




### Security / SSRF (Phase 1a)




- S7 (High): multicast `224.0.0.0/4`, `ff00::/8` now rejected in `resolve_public_addresses()` (was passing `is_global`-only).
- S8 (Medium): port allowlist — only TCP 80/443 plus operator-configured ports in `ALLOWED_PORTS` are reachable; arbitrary ports rejected at parse time.
- S10 (Low): HTTPS→HTTP redirect downgrade now blocked on every hop.
- S9 (Medium, latent): DNS-rebinding TOCTOU in JS-render path is gated behind `render_js_enabled=false`; see `scraper.py` and `fetch_rendered_html_document`.




### Code health




- Added `tests/test_ssrf_matrix.py` — 38 table-driven URL cases plus 31 non-public DNS answers and 20 numeric IP literals, covering S1–S10 probes.
- `_parse_target()` now distinguishes an explicitly written `:0` port from an omitted port. `http://host:0/` is rejected by the port allow-list instead of being silently rewritten to port 80; an omitted port still falls back to the scheme default (80/443).




### Test-suite corrections




- `tests/test_mcp_streamable.py` no longer hard-codes the service version; it asserts against `app.state.settings.service_version`, so a release bump needs no second edit.
- `tests/test_token_metering.py` fixtures now build `FetchedHTML.body` as `bytes` (the real contract). The previous `str` bodies made `_decode_source_text()` fail, so `html_tokens` was 0 and `tokens_saved_estimate` was vacuously 0 — the savings tests asserted nothing meaningful. With real bytes the estimate is `html_tokens - approx_tokens` (the markup the extractor strips), so the P3 test now bounds the estimate instead of demanding exactly 0.




## [1.0.0] — 2026-10-15




- Initial release.