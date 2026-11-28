"""Public discovery documentation; extraction remains authenticated."""

from fastapi import APIRouter
from fastapi import Request
from fastapi.responses import JSONResponse, PlainTextResponse

router = APIRouter()

ROBOTS_TEXT = """User-agent: *
Allow: /

# API documentation: https://bintu-api.onrender.com/docs
# AI-oriented documentation: https://bintu-api.onrender.com/llms.txt
"""

LLMS_TEXT = """# Bintu Data Extraction API

> Extract readable text from public HTTP/HTTPS HTML pages for AI clients.

## Documentation

- [API documentation](https://bintu-api.onrender.com/docs)
- [OpenAPI schema](https://bintu-api.onrender.com/openapi.json)
- [MCP endpoint](https://bintu-api.onrender.com/mcp)

## Limits and access

- HTML/XHTML only; JSON, PDF, images, and other media are unsupported.
- Maximum decoded upstream body: 1 MiB.
- Extracted text is capped at 6,000 characters in the deployed configuration.
- Token counts are approximate character-based estimates, not tokenizer counts.
- Authentication, rate limits, robots policy, and target safety checks apply.
- JavaScript rendering is available only when enabled by the operator.
- Discovery documents are public; extraction calls require valid credentials
  in production.

## MCP usage

Transport: Streamable HTTP at POST /mcp.
Tool: bintu_scrape_text.
Modes: scrape, chunk, summarize.
Use the negotiated protocol version supported by the server.
Do not assume support for a newer protocol solely from the transport name.

Example tools/call JSON-RPC body:

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"bintu_scrape_text","arguments":{"url":"https://example.com/","mode":"summarize","max_tokens":500,"render_js":false,"cache":true}}}
```

Send Content-Type: application/json and valid authentication, such as
X-API-Key, with the request. Never place credentials in a target URL.

## Cache refresh

- MCP: cache=false bypasses memory and persistent cache reads.
- REST: skip_cache=true bypasses cache reads.
- Fresh successful results may still be written to cache.
- Refresh does not bypass authentication, robots policy, or safety checks.

## REST usage

GET /api/v1/scrape/text?url=https%3A%2F%2Fexample.com%2F

Supply X-API-Key with a valid REST credential. MCP-only credentials do not
grant REST access.
"""


@router.get("/robots.txt", response_class=PlainTextResponse, include_in_schema=False)
def robots_txt():
    return PlainTextResponse(ROBOTS_TEXT)


@router.get("/llms.txt", response_class=PlainTextResponse, include_in_schema=False)
def llms_txt():
    return PlainTextResponse(LLMS_TEXT)




def protected_resource_metadata_url(request: Request) -> str:
    settings = getattr(request.app.state, "settings", None)
    configured = (getattr(settings, "oauth_resource_url", "") or "").strip().rstrip("/")
    if configured:
        return f"{configured}/.well-known/oauth-protected-resource"
    base = str(request.base_url).rstrip("/")
    return f"{base}/.well-known/oauth-protected-resource"


@router.get("/.well-known/oauth-protected-resource", include_in_schema=False)
def oauth_protected_resource_metadata(request: Request) -> JSONResponse:
    settings = getattr(request.app.state, "settings", None)
    configured_resource = (getattr(settings, "oauth_resource_url", "") or "").strip().rstrip("/")
    resource_uri = configured_resource or str(request.base_url).rstrip("/")
    raw_servers = (getattr(settings, "oauth_authorization_servers", "") or "").strip()
    servers = [item.strip() for item in raw_servers.split(",") if item.strip()]
    if not servers:
        supabase_url = (getattr(settings, "supabase_url", "") or "").strip().rstrip("/")
        if supabase_url:
            servers = [f"{supabase_url}/auth/v1"]
    payload = {
        "resource": resource_uri,
        "authorization_servers": servers,
        "bearer_methods_supported": ["header"],
        "resource_documentation": f"{resource_uri}/llms.txt",
    }
    return JSONResponse(content=payload)
