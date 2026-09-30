"""Post-deploy smoke check against a live Bintu API instance.

Usage (PowerShell):
  $env:BINTU_BASE_URL = "https://your-service.onrender.com"
  $env:BINTU_API_KEY = "your-api-key"   # required when the service has API_KEY set
  python smoke_check.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_TARGET_URL = "https://example.com/"
TIMEOUT_SECONDS = 60


def _request(url: str, headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read()
            return response.status, dict(response.headers.items()), body
    except urllib.error.HTTPError as error:
        body = error.read()
        return error.code, dict(error.headers.items()) if error.headers else {}, body


def _fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    base_url = os.getenv("BINTU_BASE_URL", "").strip().rstrip("/")
    api_key = os.getenv("BINTU_API_KEY", "").strip()
    target_url = os.getenv("BINTU_SMOKE_TARGET_URL", DEFAULT_TARGET_URL).strip()

    if not base_url:
        _fail("Set BINTU_BASE_URL to your deployed service root (e.g. https://....onrender.com).")

    print(f"Checking health at {base_url}/healthz ...")
    status, headers, body = _request(f"{base_url}/healthz")
    if status != 200:
        _fail(f"/healthz returned HTTP {status}: {body[:200]!r}")
    try:
        health = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail(f"/healthz returned non-JSON body: {error}")
    if health.get("status") != "ok":
        _fail(f"/healthz unexpected payload: {health}")
    print("OK  /healthz")

    scrape_url = (
        f"{base_url}/api/v1/scrape/text?"
        f"{urllib.parse.urlencode({'url': target_url})}"
    )
    scrape_headers = {"Accept": "application/json"}
    if api_key:
        scrape_headers["X-API-Key"] = api_key

    print(f"Checking scrape against {target_url} ...")
    status, headers, body = _request(scrape_url, headers=scrape_headers)
    if status == 401:
        _fail("Scrape returned 401. Set BINTU_API_KEY to the service API_KEY value.")
    if status != 200:
        _fail(f"Scrape returned HTTP {status}: {body[:300]!r}")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail(f"Scrape returned non-JSON body: {error}")
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        _fail(f"Scrape returned empty or missing text: {payload}")
    request_id = next((v for k, v in headers.items() if k.lower() == "x-request-id"), None)
    if not request_id:
        _fail("Scrape response missing X-Request-ID header")
    print(f"OK  /api/v1/scrape/text ({len(text)} characters)")
    print("Smoke check passed.")


if __name__ == "__main__":
    main()
