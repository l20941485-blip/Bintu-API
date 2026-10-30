"""Fetch readable text from a public URL using Bintu's REST API."""

import os
import sys
import urllib.parse
import urllib.request

base_url = os.getenv("BINTU_BASE_URL", "https://bintu-api.onrender.com").rstrip("/")
api_key = os.getenv("BINTU_API_KEY")
target_url = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"

if not api_key:
    raise SystemExit("Set BINTU_API_KEY before running this example.")

request = urllib.request.Request(
    f"{base_url}/api/v1/scrape/text?url={urllib.parse.quote(target_url, safe='')}",
    headers={"X-API-Key": api_key, "Accept": "application/json"},
)

with urllib.request.urlopen(request, timeout=30) as response:
    result = __import__("json").load(response)

print(f"url: {result['url']}")
print(f"approx_tokens: {result['approx_tokens']}")
print(f"truncated: {result['truncated']}")
print(f"cache_hit: {result['cache_hit']}")
print(f"cache_layer: {result['cache_layer']}")
print("\n--- text preview ---")
print(result["text"][:500])
