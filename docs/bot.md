# BintuBot - Compliance Reference Overview

## Crawler Identity

**Identity:** BintuBot  
**Base Version:** 1.1.0  
**User-Agent Format:** `BintuBot/<version> (+[BOT_INFO_URL]; [CONTACT_EMAIL])`

Example: `BintuBot/1.1.0 (+https://bintu-api.example.com/bot-info; ops@example.com)`

---

## Structural Signatures

### Request Format

| Header | Value |
|--------|-------|
| User-Agent | BintuBot/1.1.0 (+https://bintu-api.example.com/bot-info; ops@example.com) |
| Accept | text/html, application/xhtml+xml, */* |
| Accept-Encoding | gzip, deflate, br |
| Connection | keep-alive |

### Scraping Behavior

- HTML/XHTML pages only (text of public web content)
- Respects `robots.txt` directives
- No credentials, no cookies sent
- Maximum 1 MiB HTML response body
- Maximum 5 redirects
- 10-second request timeout

---

## Contact Mechanisms

### Compliance Inquiries

**Primary Contact:** ops@example.com  
**Support URL:** https://bintu-api.example.com/bot-info

### Header Reference

| Component | Value |
|-----------|-------|
| BOT_INFO_URL | https://bintu-api.example.com/bot-info |
| CONTACT_EMAIL | ops@example.com |

---

## Webmaster Instructions

### How to Allow BintuBot

Add the following to your `robots.txt` file at the root of your domain:

```
User-agent: BintuBot
Allow: /
```

**Example:**

```
# robots.txt
User-agent: BintuBot
Allow: /
```

### How to Block BintuBot

To block all scraping by BintuBot:

```
User-agent: BintuBot
Disallow: /
```

### Fine-Grained Control

Block specific paths:

```
User-agent: BintuBot
Disallow: /admin/
Disallow: /private/
```

Allow specific paths while blocking others:

```
User-agent: BintuBot
Allow: /public/
Disallow: /admin/
```

### Checking Your robots.txt

Verify your `robots.txt` is correctly configured:

1. Visit: `https://yourdomain.com/robots.txt`
2. Verify BintuBot entry is present
3. Test using the BintuBot User-Agent header

---

## RFC 9309 Compliance Features

### Robots Mode Toggles

| Mode | Behavior |
|------|----------|
| `enforce` (default) | Blocks scraping when `robots.txt` prohibits access (HTTP 403) |
| `warn` | Skips enforcement but logs protocol evaluation metrics |
| `off` | Skips robots.txt checking entirely |

### HTTP Status Code Mapping

| Status Code | Meaning |
|-------------|---------|
| 4xx | Authorization to parse (explicit rules found) |
| 5xx | Total access restriction block (disallow) |
| Timeout | Total access restriction block (disallow) |

### Caching

- Origin policy structures cached locally for exactly 1 hour (configurable via `robots_cache_ttl_seconds`)
- Cache keyed by normalized hostname

---

## Common Issues

### Issue: BintuBot returns 403

**Cause:** `robots.txt` explicitly disallows BintuBot  
**Solution:** Add `User-agent: BintuBot` with `Allow: /` or remove `Disallow` entries.

### Issue: BintuBot times out checking robots.txt

**Cause:** `robots.txt` server on target is slow or unreachable  
**Solution:** Configure `robots_cache_ttl_seconds` for your deployment.

### Issue: Content appears truncated

**Cause:** Target site has a `Content-Length` limit or server throttling  
**Solution:** Check target server configuration and BintuBot rate limits.

---

## Compliance Statement

BintuBot operates in compliance with standard web crawling guidelines. We respect `robots.txt` directives, do not scrape protected content without authorization, and provide clear contact information for compliance inquiries.

Report any issues or concerns to **ops@example.com**.

---

## Version History

### v1.1.0 (Current)

- Dynamic User-Agent with configurable info URL and contact email
- RFC 9309 robots.txt compliance with status code mapping
- 1-hour local policy cache
- ROBOTS_MODE toggles (enforce/warn/off)
- Upstream error interception for 401/402/403/429
