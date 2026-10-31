"""Black-box regression suite for the Bintu MCP service.

Talks to the deployed service over MCP streamable HTTP (POST /mcp), so it needs
no access to the source. Each test encodes something observed in manual testing.

Environment:
  BINTU_URL             base URL (default https://bintu-api.onrender.com)
  BINTU_TOKEN           bearer token, only if tools/call requires auth
  RENDER_JS_ENABLED     "1" once render_js is switched on in production
  PDF_TEST_URL          public PDF URL; PDF tests are skipped without it
  PRIVATE_REDIRECT_URL  a URL on a host YOU control that 302s to
                        http://169.254.169.254/ ; the redirect test is skipped
                        without it (httpbin refuses to redirect to private
                        addresses, so it cannot be used for this)
"""
import json
import os
import uuid
from dataclasses import dataclass
from typing import Optional

import httpx
import pytest

BASE_URL = os.environ.get("BINTU_URL", "https://bintu-api.onrender.com").rstrip("/")
TOKEN = os.environ.get("BINTU_TOKEN")
RENDER_JS_ENABLED = os.environ.get("RENDER_JS_ENABLED") == "1"
PDF_TEST_URL = os.environ.get("PDF_TEST_URL")
PRIVATE_REDIRECT_URL = os.environ.get("PRIVATE_REDIRECT_URL")

EXAMPLE = "https://example.com/"
LONG_PAGE = "https://www.gnu.org/licenses/gpl-3.0.html"


@dataclass
class ToolResult:
    is_error: bool
    text: str
    envelope: Optional[dict]
    code: Optional[str]  # failure code, e.g. "invalid_or_unsafe_url" or "rpc-32602"


class McpClient:
    def __init__(self) -> None:
        self.http = httpx.Client(base_url=BASE_URL, timeout=90)
        self.session_id: Optional[str] = None
        self._next_id = 0
        self._initialize()

    def _headers(self) -> dict:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        if TOKEN:
            headers["Authorization"] = f"Bearer {TOKEN}"
        return headers

    @staticmethod
    def _parse(response: httpx.Response, want_id: int) -> Optional[dict]:
        if response.status_code == 202 or not response.content:
            return None
        if "text/event-stream" in response.headers.get("content-type", ""):
            for line in response.text.splitlines():
                if line.startswith("data:"):
                    msg = json.loads(line[5:].strip())
                    if msg.get("id") == want_id:
                        return msg
            raise AssertionError("no matching JSON-RPC message in SSE stream")
        return response.json()

    def _rpc(self, method: str, params: dict) -> dict:
        self._next_id += 1
        payload = {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params}
        response = self.http.post("/mcp", json=payload, headers=self._headers())
        response.raise_for_status()
        if "mcp-session-id" in response.headers:
            self.session_id = response.headers["mcp-session-id"]
        message = self._parse(response, self._next_id)
        assert message is not None, f"empty response to {method}"
        return message

    def _initialize(self) -> None:
        self._rpc(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "bintu-regression", "version": "1.0"},
            },
        )
        note = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        self.http.post("/mcp", json=note, headers=self._headers())

    def scrape(self, url: str, **arguments) -> ToolResult:
        message = self._rpc(
            "tools/call",
            {"name": "bintu_scrape_text", "arguments": {"url": url, **arguments}},
        )
        if "error" in message:  # JSON-RPC level error, e.g. argument validation
            err = message["error"]
            return ToolResult(True, err.get("message", ""), None, f"rpc{err.get('code')}")
        result = message["result"]
        text = result["content"][0]["text"]
        if result.get("isError"):
            return ToolResult(True, text, None, text.split(":", 1)[0].strip())
        return ToolResult(False, text, json.loads(text), None)


@pytest.fixture(scope="session")
def mcp() -> McpClient:
    return McpClient()


def unique(url: str) -> str:
    """Add a throwaway query string so cache tests never collide across runs."""
    return f"{url}?bintu_ci={uuid.uuid4().hex}"


# ---------------------------------------------------------------- basics
def test_basic_scrape(mcp):
    r = mcp.scrape(EXAMPLE)
    assert not r.is_error, r.text
    assert r.envelope["chunks"][0]["text"].startswith("# Example Domain")
    assert r.envelope["tokens_saved_estimate"] > 0


def test_not_found_is_reported(mcp):
    r = mcp.scrape(f"https://example.com/{uuid.uuid4().hex}")
    assert r.is_error and r.code == "upstream_http_error"


def test_robots_txt_is_honoured(mcp):
    r = mcp.scrape("https://www.google.com/search?q=bintu")
    assert r.is_error and r.code == "blocked_by_robots"


# ---------------------------------------------------------------- cache
def test_cache_roundtrip(mcp):
    url = unique(EXAMPLE)
    first = mcp.scrape(url)
    second = mcp.scrape(url)
    bypass = mcp.scrape(url, cache=False)
    assert first.envelope["cache_hit"] is False
    assert second.envelope["cache_hit"] is True
    assert bypass.envelope["cache_hit"] is False


def test_persist_false_skips_persistent_layer(mcp):
    url = unique(EXAMPLE)
    mcp.scrape(url, persist=False)
    again = mcp.scrape(url)
    assert again.envelope["cache_layer"] != "persistent"


# ---------------------------------------------------------------- modes / limits
def test_scrape_truncates_to_budget(mcp):
    r = mcp.scrape(LONG_PAGE)
    env = r.envelope
    assert env["truncated"] is True
    assert env["limiting_factor"] == "token_budget"
    assert env["tokens"] <= 6000


def test_chunks_respect_budget(mcp):
    r = mcp.scrape(LONG_PAGE, mode="chunk", max_tokens=1000)
    env = r.envelope
    assert env["chunk_count"] > 1
    assert all(chunk["tokens"] <= 1000 for chunk in env["chunks"])


def test_summarize_is_truncation_not_ai_summary(mcp):
    # Documents current behaviour. If summarize ever becomes a real summary,
    # update this test and the tool description together.
    r = mcp.scrape(LONG_PAGE, mode="summarize", max_tokens=100)
    assert r.envelope["tokens"] <= 100 and r.envelope["truncated"] is True


@pytest.mark.parametrize("arguments", [{"max_tokens": 5}, {"mode": "bogus"}])
def test_bad_parameters_are_rejected(mcp, arguments):
    assert mcp.scrape(EXAMPLE, **arguments).is_error


# ---------------------------------------------------------------- security
UNSAFE_URLS = [
    "http://127.0.0.1/",
    "http://localhost/",
    "http://[::1]/",
    "http://0.0.0.0/",
    pytest.param(
        "http://2130706433/",  # decimal form of 127.0.0.1
        marks=pytest.mark.xfail(
            strict=False,
            reason="observed: generic 'connector server error' instead of invalid_or_unsafe_url",
        ),
    ),
    "http://0x7f000001/",  # hex
    "http://0177.0.0.1/",  # octal
    "http://127.1/",  # shortened
    "http://[::ffff:127.0.0.1]/",  # IPv4-mapped IPv6
    "http://169.254.169.254/latest/meta-data/",
    "http://metadata.google.internal/",
    "http://10.0.0.1/",
    "http://192.168.0.1/",
    "http://example.com@127.0.0.1/",  # credentials trick
    "https://example.com:8443/",  # non-standard port
    "ftp://example.com/",
    "file:///etc/passwd",
    "javascript:alert(1)",
]


@pytest.mark.parametrize("url", UNSAFE_URLS)
def test_unsafe_urls_are_rejected_cleanly(mcp, url):
    r = mcp.scrape(url)
    assert r.is_error, "unsafe URL was fetched"
    assert r.code == "invalid_or_unsafe_url", r.text


@pytest.mark.skipif(not PRIVATE_REDIRECT_URL, reason="needs a redirector you control")
def test_redirect_into_private_network_is_blocked(mcp):
    r = mcp.scrape(PRIVATE_REDIRECT_URL)
    assert r.is_error and r.code == "redirect_to_private_network", r.text


# ---------------------------------------------------------------- JS rendering
JS_ONLY_PAGE = f"{BASE_URL}/docs"  # Swagger UI is built client-side


@pytest.mark.skipif(RENDER_JS_ENABLED, reason="render_js is enabled")
def test_render_js_disabled_contract(mcp):
    assert mcp.scrape(EXAMPLE, render_js=True).code == "render_js_disabled"
    r = mcp.scrape(JS_ONLY_PAGE)
    assert r.envelope["low_yield"] is True


@pytest.mark.skipif(not RENDER_JS_ENABLED, reason="render_js is not enabled yet")
def test_render_js_returns_client_rendered_content(mcp):
    r = mcp.scrape(JS_ONLY_PAGE, render_js=True)
    assert not r.is_error, r.text
    assert r.envelope["low_yield"] is False and r.envelope["tokens"] > 50


@pytest.mark.skipif(not RENDER_JS_ENABLED, reason="render_js is not enabled yet")
def test_browser_cannot_be_used_to_reach_private_addresses(mcp):
    # Every request the browser makes (subresources, redirects) must pass the
    # same checks as the top-level URL.
    r = mcp.scrape("http://127.0.0.1/", render_js=True)
    assert r.is_error and r.code == "invalid_or_unsafe_url"


# ---------------------------------------------------------------- PDF
@pytest.mark.skipif(not PDF_TEST_URL, reason="PDF_TEST_URL not set")
def test_pdf_text_is_extracted(mcp):
    r = mcp.scrape(PDF_TEST_URL)
    assert not r.is_error, r.text
    assert r.envelope["tokens"] > 50


# ---------------------------------------------------------------- operations
@pytest.mark.xfail(strict=False, reason="Bintu-API has no health check path yet")
def test_healthz_endpoint():
    assert httpx.get(f"{BASE_URL}/healthz", timeout=30).status_code == 200
