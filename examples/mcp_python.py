"""Call Bintu's MCP tool using the Streamable HTTP endpoint."""

import json
import os
import sys
import urllib.request

base_url = os.getenv("BINTU_BASE_URL", "https://bintu-api.onrender.com").rstrip("/")
api_key = os.getenv("BINTU_API_KEY")
target_url = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"

if not api_key:
    raise SystemExit("Set BINTU_API_KEY before running this example.")

payload = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
        "name": "bintu_scrape_text",
        "arguments": {
            "url": target_url,
            "mode": "scrape",
            "max_tokens": 2000,
        },
    },
}

request = urllib.request.Request(
    f"{base_url}/mcp",
    data=json.dumps(payload).encode("utf-8"),
    headers={
        "X-API-Key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    },
    method="POST",
)

with urllib.request.urlopen(request, timeout=30) as response:
    envelope = json.load(response)

if "error" in envelope:
    raise SystemExit(f"MCP error: {json.dumps(envelope['error'], indent=2)}")

content = envelope["result"]["content"][0]["text"]
print(content[:1000])
