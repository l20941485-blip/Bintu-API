# Security Notes

## JavaScript rendering

Keep `RENDER_JS_ENABLED=false`.

The JavaScript-rendering path has a documented DNS-rebinding
time-of-check-to-time-of-use risk. Do not enable it until its DNS validation,
connection targeting, redirects, and browser subresource requests have been
hardened and tested.

Paid infrastructure may address resource costs; it does not resolve this
security risk. The plain-HTML fetcher's connection-pinning protections must
not be assumed to cover browser traffic.

## Plain-HTML fetching

The guarded fetcher implements destination validation and connection pinning.
Controls include rejection of non-public destinations, embedded URL
credentials, unsupported schemes, disallowed ports, and HTTPS-to-HTTP
redirect downgrades. Redirect destinations are revalidated.

These are implemented defenses, not a guarantee that every possible SSRF
technique or deployment configuration is safe. Changes to fetching, DNS,
redirect handling, proxies, or rendering require security regression tests.

## Reader authentication and continuation

The REST reader requires a configured direct API key or a verified gateway
subscriber identity, including when other routes permit open development
access.

Snapshot ownership is credential-level. Callers sharing the direct API key
share one owner identity; this is not person-level isolation.

Continuation handles are opaque and caller-bound. Treat them as sensitive
temporary values. Unknown, expired, evicted, and wrong-owner handles return
the same unavailable response.

Snapshots are retained in bounded process-local memory. They are not shared
between workers or instances and are lost on restart. Expiry limits access;
it is not a promise of immediate physical memory erasure. See README.md for
retention limits and deployment constraints.

## Credentials, logs, and retained data

Do not put API keys, provider secrets, database service credentials,
continuation handles, or sensitive extracted content in public issues,
logs, screenshots, or committed examples.

The legacy scraping cache and reader snapshot store are separate mechanisms.
Do not assume their retention, persistence, or ownership rules are identical.

If a credential is exposed, rotate it and review affected logs, repository
history, and downstream access. Deleting the visible copy alone does not
revoke the credential.

## Reporting a suspected vulnerability

Do not publish exploit details or credentials in a public issue. Use an
operator-provided private reporting channel. This repository does not
currently specify a verified security contact; do not treat example contact
addresses in documentation as working reporting channels.
