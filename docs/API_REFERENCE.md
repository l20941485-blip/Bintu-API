# API reference

This page consolidates the public Bintu REST and MCP interfaces. For
interactive request testing, open `/docs`; for the machine-readable OpenAPI
schema, open `/openapi.json`.

## Base URL

```text
[https://bintu-api.onrender.com](https://bintu-api.onrender.com)
```

## Authentication

| Surface | Header | Accepted credentials |
|---|---|---|
| REST | `X-API-Key` | Master `API_KEY`; MCP-only keys do not unlock REST routes |
| MCP | `X-API-Key` or `Authorization: Bearer` | Scoped `MCP_API_KEY` or master `API_KEY` |

Strict authentication is enabled when `API_KEY` or `RAPIDAPI_PROXY_SECRET` is
configured. Requests without a valid credential receive `401 invalid_api_key`.

## REST endpoints

### `GET /healthz`

Returns service health information.

```http
GET /healthz
```

Response fields:

| Field | Type | Description |
|---|---|---|
| `status` | string | `ok` when the service is healthy |
| `service` | string | Service name |
| `version` | string | Deployed application version |
| `environment` | string | Deployment environment |

### `GET /version`

Returns the deployed application version.

```http
GET /version
```

Response fields:

| Field | Type | Description |
|---|---|---|
| `version` | string | Semantic application version |
| `service` | string | Service name |
| `environment` | string | Deployment environment |

### `GET /metrics`

Returns Prometheus-format service metrics.

```http
GET /metrics
```

Response: `text/plain; version=0.0.4`

### `POST /v1/extract-text`

Extracts readable text from a public HTML page.

```http
POST /v1/extract-text
Content-Type: application/json
X-API-Key: <your-rest-api-key>

{
  "url": "[https://example.com/article](https://example.com/article)",
  "max_tokens": 12000,
  "chunk": false
}
```

Request fields:

| Field | Type | Required | Default | Description |
|---|---:|---:|---:|---|
| `url` | string | Yes | — | Public `http://` or `https://` HTML URL |
| `max_tokens` | integer | No | `12000` | Approximate output-token budget |
| `chunk` | boolean | No | `false` | Return text in continuation chunks |
| `chunk_index` | integer | No | `0` | Chunk to request when `chunk=true` |

Response fields:

| Field | Type | Description |
|---|---|---|
| `url` | string | Final URL after redirects |
| `title` | string or null | Extracted page title |
| `content` | string | Extracted readable text |
| `approx_tokens` | integer | Estimated tokens, calculated as `ceil(characters / 4)` |
| `truncated` | boolean | Whether output was shortened |
| `limiting_factor` | string | `char_cap`, `token_budget`, or `none` |
| `low_yield` | boolean | Whether very little readable text was extracted |
| `yield_hint` | string or null | Guidance for low-yield responses |
| `chunk` | boolean | Whether chunk mode is active |
| `chunk_index` | integer | Current chunk index |
| `has_more` | boolean | Whether another chunk is available |
| `next_chunk_index` | integer or null | Index of the next chunk |
| `cache` | string | Cache result: `hit`, `miss`, or `disabled` |
| `request_id` | string | Request correlation identifier |

## MCP tool

### `bintu_scrape_text`

Extracts readable text from a public HTML page through the MCP interface.

Tool input:

| Field | Type | Required | Default | Description |
|---|---:|---:|---:|---|
| `url` | string | Yes | — | Public `http://` or `https://` HTML URL |
| `max_tokens` | integer | No | `12000` | Approximate output-token budget |
| `chunk` | boolean | No | `false` | Return text in continuation chunks |
| `chunk_index` | integer | No | `0` | Chunk to request when `chunk=true` |

The tool returns the same core extraction fields as the REST endpoint, plus
MCP-specific metadata where applicable.

## Error codes

| HTTP status | `detail.code` | Meaning |
|---:|---|---|
| 400 | `invalid_or_unsafe_url` | URL is missing, malformed, private, or unsafe |
| 400 | `invalid_request` | Request body or parameters are invalid |
| 401 | `invalid_api_key` | Credential is missing, invalid, or unauthorized for the route |
| 403 | `blocked_by_robots` | Target robots.txt disallows the request |
| 403 | `robots_unreachable` | robots.txt could not be retrieved while enforcement is enabled |
| 413 | `payload_too_large` | Target HTML exceeds the 1 MiB limit |
| 415 | `unsupported_media_type` | Target is not HTML or XHTML |
| 429 | `burst_rate_limit_exceeded` | Short-term rate limit exceeded |
| 500 | `internal_error` | Unexpected service error |
| 500 | `auth_misconfiguration` | Strict auth is enabled without a valid service credential |
| 502 | `unsupported_content_encoding` | Target uses unsupported or invalid compression |
| 502 | `upstream_http_error` | Target returned an HTTP error |
| 504 | `upstream_timeout` | Target did not respond in time |

## Limits

| Limit | Value |
|---|---:|
| Maximum target HTML size | 1 MiB |
| Default approximate token budget | 12,000 |
| Supported target formats | HTML and XHTML |
| Supported URL schemes | HTTP and HTTPS |
| JavaScript rendering | Disabled unless enabled by the operator |

## Request correlation

Send the `X-Request-ID` response header when reporting an issue. It correlates
the request with service logs without exposing credentials or extracted content.
