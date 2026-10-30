# Support and troubleshooting

This guide helps API consumers diagnose the most common Bintu requests and
responses. Always include the `X-Request-ID` response header when contacting
support; it correlates a request with service logs without exposing secrets.

## Authentication

| Symptom | Cause | Fix |
|---|---|---|
| `401 invalid_api_key` | Missing, malformed, or incorrect REST credential | Send the master `API_KEY` in `X-API-Key`. An MCP-only key does not unlock REST routes. |
| MCP `401` | Missing or invalid MCP credential | Send the scoped `MCP_API_KEY` or master `API_KEY` as `X-API-Key`, or use `Authorization: Bearer`. |
| `500 auth_misconfiguration` | Strict authentication is enabled but no valid service credential is configured | Restore `API_KEY` or `RAPIDAPI_PROXY_SECRET` in the deployment environment, then redeploy. |

Never place an API key in a URL. Send it only in a request header.

## URL restrictions

| Symptom | Cause | Fix |
|---|---|---|
| `400 invalid_or_unsafe_url` | URL is missing, malformed, private, non-HTTP(S), or otherwise unsafe | Use a publicly reachable `http://` or `https://` URL. |
| `403 blocked_by_robots` | The target site disallows Bintu in `robots.txt` | Use a page the site owner permits; Bintu respects robots directives. |
| `403 robots_unreachable` | `robots.txt` could not be retrieved while enforcement is enabled | Try another permitted source or ask the site owner to make `robots.txt` available. |

Bintu does not bypass logins, paywalls, CAPTCHAs, or anti-bot controls.

## Content limitations

| Symptom | Cause | Fix |
|---|---|---|
| `413 payload_too_large` | The target HTML exceeds the 1 MiB limit | Use a smaller or print-friendly version of the page. |
| `415 unsupported_media_type` | Target is not HTML or XHTML | Use an HTML page; PDFs, images, videos, and JSON are not supported. |
| `502 unsupported_content_encoding` | Target returned unsupported or invalid compression | Try another URL or retry later. |
| `502 upstream_http_error` | Target returned an HTTP error | Retry later or use another source. |
| `504 upstream_timeout` | Target did not respond in time | Retry later or use a faster, server-rendered source. |

## Token budgets and truncation

`approx_tokens` is an estimate calculated as `ceil(characters / 4)`; it is not
a tokenizer-exact count.

- If `truncated` is `true`, the returned content was shortened.
- Check `limiting_factor`:
  - `char_cap`: the extracted-text character limit applied.
  - `token_budget`: the requested `max_tokens` limit applied.
  - `none`: no limit shortened the response.
- For long documents, use chunk mode or request a continuation rather than
  increasing `max_tokens` indefinitely.

## Low-yield pages

If `low_yield` is `true`, the page returned very little readable text.

- Read `yield_hint`.
- Try a print, AMP, RSS, or server-rendered version of the page.
- Confirm the page is publicly accessible without a login.
- JavaScript rendering is disabled unless the service operator enables it.

## Rate limits

A `429 burst_rate_limit_exceeded` response means the caller exceeded the
short-term burst limit.

- Pause for the number of seconds in the `Retry-After` response header.
- Avoid retrying immediately.
- Cache results when your application repeatedly requests the same page.

## MCP calls

Use tool name `bintu_scrape_text`.

| Symptom | Fix |
|---|---|
| `unknown_tool` | Call `bintu_scrape_text`; it is the only supported tool. |
| `invalid_tool_arguments` | Check the tool input schema; provide a valid public `url`. |
| `render_js_disabled` | Retry with `render_js=false`; JavaScript rendering is disabled unless enabled by the operator. |
| `premium_required` | Send a valid MCP credential or subscribe through the provided upgrade URL. |

## Reporting an issue

Include:

- The `X-Request-ID` response header
- HTTP status code
- Response `detail.code`
- Target URL, if safe to share
- Timestamp and whether the issue is constant or intermittent
- A short excerpt of returned text, if relevant

Do not send API keys, bearer tokens, passwords, or full extracted page content.
