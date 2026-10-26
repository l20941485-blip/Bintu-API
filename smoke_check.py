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
UNSAFE_TARGET_URL = "http://127.0.0.1/"
TIMEOUT_SECONDS = 60


def _request(
    url: str,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(
        url,
        headers=headers or {},
        method="GET",
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=TIMEOUT_SECONDS,
        ) as response:
            body = response.read()
            return (
                response.status,
                dict(response.headers.items()),
                body,
            )
    except urllib.error.HTTPError as error:
        body = error.read()
        return (
            error.code,
            dict(error.headers.items()) if error.headers else {},
            body,
        )


def _fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def _header(
    headers: dict[str, str],
    name: str,
) -> str | None:
    name = name.lower()
    for key, value in headers.items():
        if key.lower() == name:
            return value
    return None


def _metric_value(metrics_text: str, name: str) -> float:
    """Sum a Prometheus metric across labeled and unlabeled series."""
    total = 0.0
    labeled_prefix = f"{name}{{"

    for line in metrics_text.splitlines():
        if line.startswith(f"{name} "):
            total += float(line.split()[1])
        elif line.startswith(labeled_prefix):
            value_text = line.rsplit(" ", 1)[1]
            total += float(value_text)

    return total


def _check_metrics(base_url: str, api_key: str) -> None:
    print("Checking metrics ...")

    status, headers, body = _request(
        f"{base_url}/metrics",
        headers={"X-API-Key": api_key},
    )

    if status == 401:
        _fail(
            "/metrics returned 401. Set BINTU_API_KEY to the "
            "service API_KEY value."
        )
    if status != 200:
        _fail(f"/metrics returned HTTP {status}: {body[:300]!r}")

    metrics_text = body.decode("utf-8", errors="replace")

    cache_hits = _metric_value(
        metrics_text,
        "bintu_cache_hits_total",
    )
    cache_misses = _metric_value(
        metrics_text,
        "bintu_cache_misses_total",
    )
    tokens_saved = _metric_value(
        metrics_text,
        "bintu_tokens_saved_estimate_total",
    )

    cache_lookups = cache_hits + cache_misses
    cache_hit_rate = (
        cache_hits / cache_lookups if cache_lookups else 0.0
    )

    print("OK  /metrics")
    print(f"    cache hits: {cache_hits:.0f}")
    print(f"    cache misses: {cache_misses:.0f}")
    print(f"    cache hit rate: {cache_hit_rate:.1%}")
    print(f"    estimated tokens saved: {tokens_saved:.0f}")


def main() -> None:
    base_url = os.getenv("BINTU_BASE_URL", "").strip().rstrip("/")
    api_key = os.getenv("BINTU_API_KEY", "").strip()
    target_url = os.getenv(
        "BINTU_SMOKE_TARGET_URL",
        DEFAULT_TARGET_URL,
    ).strip()

    if not base_url:
        _fail(
            "Set BINTU_BASE_URL to your deployed service root "
            "(e.g. https://....onrender.com)."
        )

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

    scrape_headers = {"Accept": "application/json"}
    if api_key:
        scrape_headers["X-API-Key"] = api_key

    scrape_url = (
        f"{base_url}/api/v1/scrape/text?"
        f"{urllib.parse.urlencode({'url': target_url})}"
    )

    print(f"Checking scrape against {target_url} ...")
    status, headers, body = _request(
        scrape_url,
        headers=scrape_headers,
    )
    if status == 401:
        _fail(
            "Scrape returned 401. Set BINTU_API_KEY to the "
            "service API_KEY value."
        )
    if status != 200:
        _fail(f"Scrape returned HTTP {status}: {body[:300]!r}")

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail(f"Scrape returned non-JSON body: {error}")

    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        _fail(f"Scrape returned empty or missing text: {payload}")

    request_id = _header(headers, "X-Request-ID")
    if not request_id:
        _fail("Scrape response missing X-Request-ID header")

    print(
        f"OK  /api/v1/scrape/text ({len(text)} characters)"
    )

    unsafe_url = (
        f"{base_url}/api/v1/scrape/text?"
        f"{urllib.parse.urlencode({'url': UNSAFE_TARGET_URL})}"
    )

    print(
        "Checking unsafe URL rejection for "
        f"{UNSAFE_TARGET_URL} ..."
    )
    status, headers, body = _request(
        unsafe_url,
        headers=scrape_headers,
    )
    if status != 400:
        _fail(
            f"Unsafe URL returned HTTP {status}; expected 400: "
            f"{body[:300]!r}"
        )

    try:
        unsafe_payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail(f"Unsafe URL response was not JSON: {error}")

    detail = unsafe_payload.get("detail")
    if not isinstance(detail, dict):
        _fail(
            "Unsafe URL response detail is not an object: "
            f"{unsafe_payload}"
        )

    if detail.get("code") != "invalid_or_unsafe_url":
        _fail(
            "Unsafe URL response does not use "
            "invalid_or_unsafe_url: "
            f"{unsafe_payload}"
        )

    if UNSAFE_TARGET_URL in body.decode(
        "utf-8",
        errors="replace",
    ):
        _fail("Unsafe URL response leaked the requested URL.")

    print("OK  unsafe URL rejected with invalid_or_unsafe_url")

    if api_key:
        _check_metrics(base_url, api_key)
    else:
        print("SKIP /metrics (BINTU_API_KEY is not set)")

    print("Smoke check passed.")


if __name__ == "__main__":
    main()