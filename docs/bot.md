# BintuBot Reference

## Identity and contact

Outbound fetches identify the crawler as BintuBot. The User-Agent is built
from the service version and configured `BOT_INFO_URL` and `CONTACT_EMAIL`.

Operators must configure a real public information URL and monitored contact
address. Example-domain URLs and example email addresses are placeholders,
not working support or security-reporting channels.

The reviewed HTML and robots fetch paths request `Accept-Encoding: identity`.
Do not infer exact request headers from an outdated static example.

## Fetching and content

Bintu extracts text from supported public HTML/XHTML pages through the
guarded fetcher. Upstream size, redirect, destination-validation, and
media-type controls apply.

Keep JavaScript rendering disabled until the security prerequisites in
root SECURITY.md are satisfied. Paid infrastructure alone does not resolve
the documented rendering risk.

Fetched text remains untrusted content. Bintu is not a prompt-injection
sanitizer or malware scanner.

## Robots policy

`ROBOTS_MODE` controls enforcement:

| Mode | Behavior |
|---|---|
| `enforce` | Default. Denials and retrieval failures block page fetching. |
| `warn` | Evaluate policy, log denials or retrieval failures, and continue. |
| `off` | Skip robots checking. |

In enforce mode:

- Explicit policy denial returns HTTP 403 with `blocked_by_robots`.
- Retrieval failure returns HTTP 403 with `robots_unreachable`.

The reviewed robots fetcher treats HTTP 4xx responses as no rules retrieved.
Other unsuccessful non-redirect statuses, including 5xx, produce a retrieval
failure. Network failures and timeouts also produce a retrieval failure.
This summarizes implementation behavior, not a blanket standards-compliance
guarantee.

Policy entries are cached by origin, including scheme and effective port.
The normal lifetime defaults to 3600 seconds and is configurable with
`ROBOTS_CACHE_TTL_SECONDS`. Retrieval failures use a separate cache lifetime.
Not all outcomes are cached for exactly one hour.

## Webmaster controls

To block BintuBot, publish this at the origin's `/robots.txt`:

```text
User-agent: BintuBot
Disallow: /
```

To allow BintuBot:

```text
User-agent: BintuBot
Allow: /
```

To disallow specific paths:

```text
User-agent: BintuBot
Disallow: /admin/
Disallow: /private/
```

Changes may not affect an already cached decision immediately.
Keep enforcement enabled; do not bypass site policy to troubleshoot
extraction.

## Troubleshooting

### HTTP 403

Inspect `detail.code` rather than assuming every 403 is a policy denial:

- `blocked_by_robots`: the evaluated policy disallows the requested path.
- `robots_unreachable`: the service could not retrieve a usable policy.

Use the response's `X-Request-ID` when reporting a problem.

### Missing or shortened content

Check the selected endpoint's limits and response metadata. Legacy scrape
responses can be truncated by their character cap. The reader instead
rejects extractions above its retention limit and pages retained text
through continuation handles.

JavaScript-dependent content may be absent from plain HTML. Changing robots
cache settings does not repair extraction limits or JavaScript-dependent
content.

See README.md for endpoint contracts and DEPLOYMENT.md for release validation.
