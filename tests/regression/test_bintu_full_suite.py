import os
import json
import time
import requests

BASE_URL = os.getenv("BINTU_BASE_URL", "https://bintu-api.onrender.com")
MCP_URL = os.getenv("BINTU_MCP_URL", "https://bintu-web-reader.mcpize.run/mcp")
API_KEY = os.getenv("BINTU_API_KEY", "sk_db0ea0ab5b5b4d0c9c633834e13abd8f")

results = []

def run_test(name, func):
    print(f"[-] Testing [{name}]...", end=" ")
    try:
        success, message = func()
        if success:
            print("✅ PASSED")
            results.append({"test": name, "status": "PASSED", "details": message})
        else:
            print(f"❌ FAILED: {message}")
            results.append({"test": name, "status": "FAILED", "details": message})
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        results.append({"test": name, "status": "ERROR", "details": str(e)})

def test_health():
    resp = requests.get(f"{BASE_URL}/healthz", timeout=10)
    if resp.status_code == 200 and resp.json().get("status") == "ok":
        return True, "Health check route returned status ok"
    return False, f"Unexpected code/body: {resp.status_code} {resp.text}"

def test_version():
    resp = requests.get(f"{BASE_URL}/version", timeout=10)
    if resp.status_code in [200, 401]:
        return True, f"Version endpoint accessible (Status {resp.status_code})"
    return False, f"Unexpected status: {resp.status_code}"

def test_rest_scrape():
    target = "https://www.iana.org/domains/reserved"
    headers = {"X-API-Key": API_KEY}
    resp = requests.get(f"{BASE_URL}/api/v1/scrape/text", params={"url": target}, headers=headers, timeout=15)
    if resp.status_code == 200:
        data = resp.json()
        if "text" in data and "approx_tokens" in data and "truncated" in data:
            return True, f"Extracted {len(data['text'])} chars, approx {data['approx_tokens']} tokens (Truncated: {data['truncated']})"
    return False, f"HTTP {resp.status_code}: {resp.text}"

def test_rest_chunks():
    target = "https://www.iana.org/domains/reserved"
    headers = {"X-API-Key": API_KEY}
    body = {"url": target, "include_nav": False, "include_header": False, "include_footer": False, "render_js": False}
    resp = requests.post(f"{BASE_URL}/api/v1/scrape/chunks?max_tokens=1000", json=body, headers=headers, timeout=15)
    if resp.status_code == 200:
        data = resp.json()
        if data.get("mode") == "chunk" and "chunks" in data:
            return True, f"Chunk mode generated {data.get('chunk_count')} chunks successfully"
    return False, f"HTTP {resp.status_code}: {resp.text}"

def test_mcp_discovery():
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    resp = requests.post(MCP_URL, json=payload, headers=headers, timeout=15)
    if resp.status_code == 200:
        tools = resp.json().get("result", {}).get("tools", [])
        if any(t.get("name") == "bintu_scrape_text" for t in tools):
            return True, "Successfully discovered bintu_scrape_text tool schema"
    return False, f"HTTP {resp.status_code}: {resp.text}"

def test_mcp_execution():
    payload = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "bintu_scrape_text", "arguments": {"url": "https://example.com", "max_tokens": 500}}}
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    resp = requests.post(MCP_URL, json=payload, headers=headers, timeout=15)
    if resp.status_code == 200:
        data = resp.json()
        if "result" in data:
            return True, "MCP tools/call executed and returned extraction envelope"
    return False, f"HTTP {resp.status_code}: {resp.text}"

def test_error_invalid_url():
    headers = {"X-API-Key": API_KEY}
    resp = requests.get(f"{BASE_URL}/api/v1/scrape/text", params={"url": "htp:/invalid-url"}, headers=headers, timeout=10)
    if resp.status_code == 400:
        error_detail = resp.json().get("detail", {})
        if error_detail.get("code") == "invalid_or_unsafe_url":
            return True, "Correctly rejected malformed URL with code 'invalid_or_unsafe_url'"
    return False, f"Expected HTTP 400 with invalid_or_unsafe_url code, got {resp.status_code}: {resp.text}"

def test_error_unauthorized():
    headers = {"X-API-Key": "wrong_key_12345"}
    resp = requests.get(f"{BASE_URL}/api/v1/scrape/text", params={"url": "https://example.com"}, headers=headers, timeout=10)
    if resp.status_code == 401:
        return True, "Correctly rejected invalid credentials with HTTP 401"
    return False, f"Expected HTTP 401, got {resp.status_code}"

if __name__ == "__main__":
    print("=" * 70)
    print("🚀 BINTU API & MCP CONNECTOR - FULL FEATURE CLAIM VALIDATION SUITE")
    print("=" * 70)
    run_test("Render Health Check (/healthz)", test_health)
    run_test("Service Version Route (/version)", test_version)
    run_test("REST Text Scrape (/api/v1/scrape/text)", test_rest_scrape)
    run_test("REST Chunk Scrape (/api/v1/scrape/chunks)", test_rest_chunks)
    run_test("MCP Tool Discovery (tools/list)", test_mcp_discovery)
    run_test("MCP Tool Execution (tools/call)", test_mcp_execution)
    run_test("Error Validation: Invalid URL (400)", test_error_invalid_url)
    run_test("Error Validation: Unauthorized Key (401)", test_error_unauthorized)
    print("\n" + "=" * 70)
    print("📊 FINAL FEATURE VALIDATION SUMMARY REPORT")
    print("=" * 70)
    passed = sum(1 for r in results if r["status"] == "PASSED")
    total = len(results)
    for r in results:
        status_icon = "✅" if r["status"] == "PASSED" else "❌"
        print(f"{status_icon} [{r['test']}] -> {r['status']}: {r['details']}")
    print("-" * 70)
    success_rate = (passed / total) * 100 if total > 0 else 0
    print(f"Overall Success Rate: {passed}/{total} ({success_rate:.1f}%)")
    print("=" * 70)
