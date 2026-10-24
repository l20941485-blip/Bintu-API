# Bintu Security Notes

## JavaScript Rendering

JavaScript rendering (Playwright/Chromium) is **disabled by default** and must stay off until validation and connection share one DNS resolution. The service uses `_is_multicast_address` and `_is_nat64_or_6to4_address` guards plus pinned connections to prevent SSRF, but these only apply to the initial validated IP.

**Never enable `RENDER_JS_ENABLED=true` on free-tier infrastructure.** It boots Playwright/Chromium on every fetch, incurring 2-4s startup latency and ongoing RAM costs. Only enable on paid plans that cover these costs.

**Security guarantee:** As long as `render_js_enabled=false`, the SSRF guards in `scraper.py` (loopback, RFC1918, link-local, CGNAT, multicast, port allowlist, DNS rebinding via IP pinning) are sufficient. Enabling JS rendering introduces a TOCTOU vulnerability where validation and connection DNS lookups diverge.

## SSRF Prevention

The service rejects requests targeting:

- Loopback/loopback-adjacent: `127.0.0.1`, `::1`, `0.0.0.0`, `localhost`, `*.localhost`
- RFC1918 private: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`
- Link-local: `169.254.0.0/16`, `fe80::/10`
- Metadata: `169.254.169.254`
- CGNAT: `100.64.0.0/10`
- Multicast: `224.0.0.0/4`, `ff00::/8`
- NAT64/6to4 embedding private IPv4: `64:ff9b::/96`, `2002::/16`
- Ports other than 80/443 (plus configured `ALLOWED_PORTS`)
- HTTPS→HTTP downgrade on redirect
- URLs with embedded credentials
- Non-HTTP schemes (file:, ftp:, gopher:, javascript:, data:)

## Cache

- Responses are cached in memory with TTL-based expiration
- Cache keys include render_js setting to prevent cross-mode contamination