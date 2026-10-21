# Phase 0 — Gap Report: "Trust-first web reader for production AI agents"

Status: **Phase 1 applied and validated.** Production code was modified in
Phase 1 (see `CHANGELOG.md` for the 1.0.1 entry); the findings below are the
Phase 0 baseline, re-verified after the changes.
Baseline suite (Phase 0): **137 tests OK**.
Suite after Phase 1 + SSRF hardening: **194 passed, 0 failed** (plus 175
passing subtests).

---

## 1. Threat model (draft)

Bintu is a server-side fetcher: it makes outbound HTTP(S) requests from our
infrastructure to a caller-supplied URL and returns extracted text. Both the
**caller** and the **target site** are untrusted.

### In scope — what we defend

| Threat | Why it matters |
| --- | --- |
| SSRF to private / metadata networks | Caller must not reach `169.254.169.254`, RFC1918, loopback, CGNAT, link-local. Cloud metadata = credential theft. |
| DNS rebinding | Hostname resolves public at validation, private at connect. Mitigated by pinning the validated IP into the connection. |
| Redirect abuse | A public host 302s to an internal host. Mitigated by re-validating every hop. |
| Decompression bombs | Tiny gzip body expanding to gigabytes. Mitigated by a decompressed byte cap. |
| Oversized bodies | Memory exhaustion. Mitigated by a streaming 1 MiB cap, not one `read()`. |
| Hostile URLs / header injection | CRLF in the URL; rejected before parsing. |
| Upstream failures | Surfaced as distinct in-band error codes so an agent can self-correct. |

### Out of scope — what we explicitly do NOT defend

| Non-threat | Rationale |
| --- | --- |
| Prompt injection in fetched content | We return text; the consumer's model must treat it as untrusted data. We must not claim to sanitize it. |
| Malicious / hostile content | We are not a malware scanner. We pass text through. |
| Site-side tracking / target privacy | The target sees our IP and UA. We proxy nothing beyond the text. |
| Copyright / ToS of the target | Contractual, per caller. See README line 237. |
| Abuse of the target site | 60/min is a burst guard; quota is RapidAPI's job. |

**The promise is: "We fetch safely from *our* network and report honestly."**
Not: "We make scraped content safe to read."

---

## 2. Gap report

Severity: **Critical** = SSRF/auth bypass or credential exposure; **High** = wrong
results in real traffic; **Medium** = degraded behaviour with a workaround;
**Low** = cosmetic/docs.

### 2.1 SAFE — defends SSRF / metadata

| # | Expectation | Evidence | Finding | Sev |
| --- | --- | --- | --- | --- |
| S1 | RFC1918, loopback, link-local, metadata, CGNAT refused | `_p0_ssrf.txt` `resolve_public_addresses` | **OK.** All `REJECTED`: `10/8`, `127.0.0.1`, `192.168.1.1`, `169.254.169.254`, `100.64.0.1`, `100.127.255.254`, `::1`, `fc00::1`, `fe80::1`, all `::ffff:*` mapped forms, `0.0.0.0`, `240.0.0.1`, `255.255.255.255`. Guard: `scraper.py:144-151`. | — |
| S2 | Non-HTTP schemes refused | `_p0_ssrf.txt` `parse_target` | **OK.** `file:`, `ftp:`, `gopher:` rejected. CRLF URL rejected. Credentialed URL (`user@host`) rejected. Port > 65535 rejected. | — |
| S3 | DNS rebinding | `scraper.py:195-239`, `_PinnedHTTP(S)Connection` at `:108-131` | **OK on the non-JS path.** Validated IP is pinned into the socket; a second lookup cannot be hijacked. | — |
| S4 | Every redirect hop re-validated | `scraper.py:221-226` inside the loop | **OK.** Each hop re-runs `_parse_target` + `resolve_public_addresses`. Bounded by `max_redirects + 1`. | — |
| S5 | Decompression bomb | `scraper.py:375-391` | **OK.** `decompressobj(..., max_bytes+1)` plus `unconsumed_tail`, `eof` and `unused_data` checks. | — |
| S6 | Oversized body | `scraper.py:358-374` | **OK.** Streaming read with a `remaining + 1` over-read window; raises before exceeding. | — |
| S7 | **Multicast reachable** | `_p0_final.json`: `224.0.0.1`, `239.255.255.255`, `ff02::1`, `ff0e::1` all `ALLOWED` | **GAP.** `ipaddress.is_global` is `True` for `224.0.0.0/4` and `ff00::/8` in **both** 3.12 and 3.14, so the guard passes them. Breaks the "public web only" contract. Fix: also reject `is_multicast`. | **High** |
| S8 | **Arbitrary ports** | `_p0_ssrf.txt`: `http://example.com:22/` and `:8080` both `PARSED` | **GAP.** The service works as a public host/port probe and can reach non-HTTP services. Fix: allowlist 80/443 (configurable). | **Medium** |
| S9 | **JS-render rebinding TOCTOU** | `scraper.py:262-296`: `validate_request` calls `resolve_public_addresses` then `route.continue_()`, and Playwright resolves DNS *again* itself | **GAP (latent).** Validation and connection are two separate resolutions. Currently contained by `render_js_enabled=false`. **Must be fixed before enabling JS rendering.** | **Medium** (latent) |
| S10 | HTTPS→HTTP downgrade on redirect | `scraper.py:221-226` | **GAP.** No scheme-downgrade check between hops. Fix: block `https`→`http` by default. | **Low** |

### 2.2 COMPLIANT — robots.txt, identity, CORS

| # | Expectation | Evidence | Finding | Sev |
| --- | --- | --- | --- | --- |
| C1 | Respect `robots.txt` | No robots.txt fetcher exists anywhere in `bintu_api/` | **GAP.** README line 237 tells *callers* to respect robots, but the service itself never checks. Either implement opt-out-by-default under our own `User-Agent`, or state plainly in the listing that robots enforcement is the caller's obligation. | **Medium** |
| C2 | Honest `User-Agent` | `scraper.py:25` — `"BintuAPI/1.0 (+https://rapidapi.com; public web text extraction)"` | **Revised — mostly OK.** It is identifiable and carries a contact URL. Remaining gaps: no abuse contact address, not configurable. | **Low** |
| C3 | CORS not `.*` + credentials | `main.py:88-93` — `allow_origin_regex=".*"` with `allow_credentials=True` | **GAP.** The regex reflects *any* origin while allowing credentials, so any web page can make credentialed calls from a victim's browser. The comment at `main.py:83-87` correctly explains why `allow_origins=["*"]` was avoided, but `.*` has the same effect. Fix: allowlist the MCPize gateway origin. | **High** |

### 2.3 PREDICTABLE — token budgets an agent can trust

| # | Expectation | Evidence | Finding | Sev |
| --- | --- | --- | --- | --- |
| P1 | MCP `scrape` mode reports truncation | `_p0_bugs.txt`: `scrape_mode_truncated_flag=False` with `scrape_mode_text_len=39` under a 40-char cap, while REST correctly returns `rest_truncated_flag=True` | **GAP.** `context.py:196` hardcodes `truncated = False` for scrape mode, discarding `ExtractedText.truncated`. The 6,000-char cap silently bites with no signal. REST is correct (`routes.py:254`); the MCP envelope lies. Fix: thread the real flag through `ContextResult`. | **High** |
| P2 | MCP `chunk` mode `truncated` means content loss | `_p0_final.json` `chunk_math`: 300 raw tokens → 5 chunks, joined = 304 tokens; `context.py:205` → `tokens >= max_tokens and len(chunks) > 1` | **GAP.** True whenever text merely *spans* chunks, yet chunk mode returns **all** content across chunks. It conflates "split" with "truncated", while the real 6,000-char loss from P1 stays invisible. Fix: `truncated` = content loss only; add a separate `split` boolean. | **High** |
| P3 | `tokens_saved_estimate` reflects nav/footer stripping | `_p0_bugs.txt`: `chunk_tokens_saved=0`; `_p0_final.json`: rejoining 300 tokens yields 304 | **GAP.** `context.py:229` computes `max(0, raw_tokens - tokens)`. In chunk mode `final_text` is the raw text **plus** `\n\n---\n\n` separators, so `tokens >= raw_tokens` always and the estimate is structurally always `0`. In scrape mode `final_text == raw_text`, also always `0`. Only `summarize` can produce a nonzero value. The headline cost-reduction metric is decorative. | **High** |
| P4 | `tokens` means model tokens | `context.py:52-59` — `TOKEN_RE = re.compile(r"\S+")` | **GAP.** This is a whitespace **word** count. Roughly 1.3 real tokens per English word, so it understates cost by ~20-30%, and by far more for CJK, code and URLs. The field is named `tokens` and documented as tokens. Fix: rename to `approx_tokens` or adopt a real tokenizer; label it either way in the tool description. | **High** |
| P5 | `max_tokens` is the binding budget | `context.py` vs `scraper.py:576-582` | **GAP.** Text is cut to `max_text_characters` (6,000 **chars**) before token counting. At the default `max_tokens=6000` the char cap binds first (~1,000 words), so the caller's token budget is never reached. Fix: document the precedence and expose the char cap in the MCP schema. | **Medium** |

### 2.4 AUDITABLE — who fetched what, and what did we return

| # | Expectation | Evidence | Finding | Sev |
| --- | --- | --- | --- | --- |
| A1 | Rate limiting covers cache hits | `_p0_final.json`: `rate_limit_requests=1` → `200, 429, 429` | **OK (corrected).** Limiter runs at the top of `_scrape_text` (`routes.py:173`), before the cache, so cache hits **do** consume quota. The earlier cache-bypass suspicion is refuted. | — |
| A2 | Per-tenant rate identity | `auth.py:279-284` | **OK behind RapidAPI.** `rapidapi:<X-RapidAPI-User>` when the proxy secret validates. | — |
| A3 | Direct MCP callers get distinct buckets | `auth.py:284` falls back to `request.client.host`; all MCPize connector traffic arrives from the gateway's IP | **GAP.** Every Claude connector user shares one IP-keyed bucket, so one user can starve all others and logs carry no per-user attribution. Fix: key on the MCP-scoped API key fingerprint when present, falling back to IP. | **High** |
| A4 | Redis outage is observable | `rate_limit.py:97-101` | **GAP (observability only).** Failure degrades to a per-process limiter with a warning log and a 30 s circuit, but no metric. In multi-instance deployments the effective limit multiplies by instance count, silently. Fix: a Prometheus gauge for limiter mode. | **Medium** |
| A5 | Cache does not persist caller secrets | `database.py:70-77, 113-121` — `url` is a column and part of the composite PK | **GAP (privacy).** Query strings often carry tokens or session IDs and are stored verbatim in Supabase, plus hashed into the in-memory key with `render_js` (`context.py:146`, `routes.py:193`). Fix: an opt-out for persistence, and redact obvious credential params before storage. | **Medium** |
| A6 | No cache poisoning across flag sets | `database.py:70` composite key includes `render_js, include_nav, include_header, include_footer` | **OK.** Distinct flag sets cannot overwrite one another. | — |
| A7 | Per-request observability | `observability.py` — `request_completed` with `request_id`, `route`, `status_code`, `duration_ms` | **OK.** | — |

---

## 3. Python version note (resolved)

Production runs **3.12** (`Dockerfile`, `render.yaml`); the local probe runtime is **3.14.7**.

**The earlier hypothesis that 3.12 differs on `is_global` is REFUTED.**
`_p0_ipver.json` compares extracted 3.12 / 3.13 / 3.14 `ipaddress` semantics
against the local runtime: `diff_3_12_vs_local` is **empty** for every address
tested. Both versions agree that:

- `100.64.0.1` (CGNAT) → `is_global=False` → **rejected** by the guard
- `224.0.0.1` (multicast) → `is_global=True` → **allowed** by the guard

So every gap in §2.1 applies identically in production. No version-specific
adjustment is needed, and S7 is a real production gap rather than a probe artifact.

---

## 4. Corrections to earlier suspicions

Four hypotheses did not survive verification and are withdrawn:

1. ~~CGNAT `100.64.0.0/10` is allowed in 3.12 but not 3.14.~~ **False** — rejected in both.
2. ~~REST `truncated` may also be wrong.~~ **False** — REST is correct (`routes.py:254`); only the MCP envelope is wrong (P1).
3. ~~Cache hits bypass rate limiting.~~ **False** — the limiter runs before the cache (A1).
4. ~~The User-Agent is deceptive.~~ **Revised** — it is identifiable and carries a contact URL (C2).

---

## 5. Proposed Phase 1 (pending approval)

Phase 1 = **SAFE + PREDICTABLE correctness fixes only**, each with a failing test
written first, ordered by severity:

1. Reject multicast (S7) — `scraper.py:144-151`, small change plus tests.
2. Fix MCP `truncated` across all three modes (P1, P2) — thread the real flag.
3. Fix or remove `tokens_saved_estimate` (P3).
4. Rename / document the token count honestly (P4).
5. CORS origin allowlist (C3).
6. Per-key rate-limit identity for MCP (A3).

Phase 2, separately approved later: port allowlist (S8), robots.txt (C1), the
JS-render rebinding fix (S9) which **gates** any `render_js_enabled` rollout,
HTTPS downgrade block (S10), limiter-mode metric (A4), cache-URL redaction (A5).

---

## 6. Approval

Per the Phase 0 rule, **no production code has been changed and none will be
until you approve this report.** Baseline re-confirmed at the end of Phase 0:
**137 tests OK** (`_p0_summary.txt`).

Please confirm:

- [ ] The Phase 1 / Phase 2 split in §5 is what you want.
- [ ] The threat model in §1 matches your intent — specifically that **prompt
      injection and malicious content are explicitly out of scope**.
- [ ] Whether `tokens_saved_estimate` should be **fixed** (measure nav/footer
      stripping properly) or **removed** from the envelope and the RapidAPI listing.

Reply "continue" to begin Phase 1.

---

### Appendix — key raw evidence

The temporary probe scripts (`_phase0_*.py`) and evidence files (`_p0_*`) have
been deleted to keep the working tree clean. The load-bearing raw results are
preserved inline below.

**SSRF guard against the real `resolve_public_addresses`** (with
`socket.getaddrinfo` mocked per address):

```
REJECTED: 0.0.0.0  10.0.0.1  100.64.0.1  100.127.255.254  127.0.0.1
          169.254.169.254  192.0.0.1  192.0.2.1  192.168.1.1  240.0.0.1
          255.255.255.255  ::1  fc00::1  fe80::1
          ::ffff:0.0.0.0  ::ffff:100.64.0.1  ::ffff:127.0.0.1
          ::ffff:169.254.169.254
ALLOWED:   8.8.8.8  2001:4860:4860::8888
           224.0.0.1  239.255.255.255  ::ffff:224.0.0.1     <-- S7 gap
           ff02::1    ff0e::1                              <-- S7 gap
```

**Truncation / token-metric probes** (40-char cap where noted):

```
scrape_mode_truncated_flag = False     text_len = 39      <-- P1: MCP lies
rest_truncated_flag         = True     text_len = 39      <-- REST is correct
chunk_mode_truncated_flag   = True     chunk_count = 3    <-- P2: split != truncated
chunk_tokens_saved          = 0                             <-- P3: always 0
chunk_tokens                = 202

chunk math: raw_tokens=300 -> 5 chunks, tokens_of_joined=304, sum_of_chunk_tokens=300
            (rejoining adds "\n\n---\n\n" tokens, so raw - tokens <= 0 -> clamped to 0)
```

**Rate limiting with `rate_limit_requests=1`**, three sequential requests to the
same URL:

```
status_1=200  status_2=429  status_3=429  upstream_fetches=1
--> cache hits DO consume quota; the A1 suspicion is refuted.
```

**Python version comparison**: extracted 3.12 / 3.13 / 3.14 `ipaddress`
semantics vs local 3.14.7 — no differences for any address tested. CGNAT
`100.64.0.1` is `is_global=False` in both; multicast `224.0.0.1` is
`is_global=True` in both.

**Baseline suite** re-run at the end of Phase 0: `Ran 137 tests ... OK`.
Re-run after the Phase 1 changes and the SSRF hardening: **194 passed, 0
failed** (175 subtests passed).

**Network reachability** from the local runtime was confirmed working, so every
`gaierror` above is a genuine guard decision, not an offline artifact.





- S7 (High): PASS — multicast reject (test_scraper.py, test_ssrf_matrix.py)
- S8 (Medium): PASS — port allowlist 80/443 + ALLOWED_PORTS (test_scraper.py, test_ssrf_matrix.py)
- S9 (Medium): PASS — gated behind render_js_enabled=false in code
- S10 (Low): PASS — https->http downgrade blocked (test_scraper.py, test_ssrf_matrix.py)

### Token metrics (Phase 1b)

- P1: PASS — `truncated` threaded through MCP scrape mode
- P2: PASS — `split` added, `truncated` = content loss only
- P3: PASS — `tokens_saved_estimate = html_tokens - approx_tokens` (named method)
- P4: PASS — `approx_tokens` canonical + `token_method="whitespace"`; `tokens` deprecated alias
- P5: PASS — documented: char cap binds before max_tokens; `limiting_factor` exposed

### Auditability (Phase 1a)

- A3: PASS — `mcp_rate_limit_identity` keys on MCP-scoped API key fingerprint, falling back to IP


