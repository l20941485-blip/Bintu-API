# Changelog

All notable changes to the Bintu Data Extraction API will be documented here.

## [1.0.1] — 2026-10-20

### Response-shape changes (Phase 1b)

- `approx_tokens` — new canonical field: approximate token count of the delivered text.
  Uses dependency-free whitespace-split tokenizer ("whitespace" method), no tiktoken dependency.
- `token_method` — new field always present: `"whitespace"` (the tokenizer method used).
- `tokens` — deprecated alias for `approx_tokens`, kept one release so existing
  clients reading `tokens` do not break.
- `tokens_saved_estimate` — **redefined**. Now equals
  `approx_tokens (fetched HTML, best-effort decode) - approx_tokens (delivered text)`,
  the "fetched HTML tokens minus delivered text tokens" estimate. Previously clamped
  to 0 in scrape/chunk modes. Named and labelled as an *estimate*.
- `split` — new boolean: `true` when chunk mode delivered multiple chunks (content
  preserved, not lost). Distinguished from `truncated` which means actual content loss.
- `truncated` — now correctly threaded through MCP `scrape` mode (was hardcoded
  `False` in `context.py`, hiding the 6,000-char char cap being hit).
- `limiting_factor` — new field: `"char_cap"` when the 6,000-char cap bound the result,
  `"token_budget"` when summarize trimmed, `"none"` otherwise. Makes the precedence
  explicit: the char cap binds before `max_tokens`.

### Security / SSRF (Phase 1a)

- S7 (High): multicast `224.0.0.0/4`, `ff00::/8` now rejected in
  `resolve_public_addresses()` (was passing `is_global`-only).
- S8 (Medium): port allowlist — only TCP 80/443 plus operator-configured ports
  in `ALLOWED_PORTS` are reachable; arbitrary ports rejected at parse time.
- S10 (Low): HTTPS→HTTP redirect downgrade now blocked on every hop.
- S9 (Medium, latent): DNS-rebinding TOCTOU in JS-render path is gated behind
  `render_js_enabled=false`; see `scraper.py` and `fetch_rendered_html_document`.

### Code health

- Added `tests/test_ssrf_matrix.py` — 38 table-driven URL cases plus 31 non-public
  DNS answers and 20 numeric IP literals, covering S1–S10 probes.
- `_parse_target()` now distinguishes an explicitly written `:0` port from an
  omitted port. `http://host:0/` is rejected by the port allow-list instead of
  being silently rewritten to port 80; an omitted port still falls back to the
  scheme default (80/443).

### Test-suite corrections

- `tests/test_mcp_streamable.py` no longer hard-codes the service version; it
  asserts against `app.state.settings.service_version`, so a release bump needs
  no second edit.
- `tests/test_token_metering.py` fixtures now build `FetchedHTML.body` as
  `bytes` (the real contract). The previous `str` bodies made
  `_decode_source_text()` fail, so `html_tokens` was 0 and
  `tokens_saved_estimate` was vacuously 0 — the savings tests asserted nothing
  meaningful. With real bytes the estimate is `html_tokens - approx_tokens`
  (the markup the extractor strips), so the P3 test now bounds the estimate
  instead of demanding exactly 0.

## [1.0.0] — 2026-10-15

- Initial release.
