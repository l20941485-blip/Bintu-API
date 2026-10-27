"""Public discovery checks for the post-deployment smoke script."""

import json
import re
import urllib.request

TIMEOUT_SECONDS = 60


def _fetch(url, payload=None):
    headers = {"Accept": "application/json, text/plain"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": "2025-11-25",
        }

    request = urllib.request.Request(
        url, data=data, headers=headers,
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return (
            response.status,
            response.headers.get_content_type(),
            response.read().decode("utf-8"),
        )


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def check_discovery(base_url):
    for path, markers in (
        ("/robots.txt", ("User-agent: *", "Allow: /", "/docs")),
        ("/llms.txt", ("bintu_scrape_text", "1 MiB", "6,000",
                       "cache=false", "skip_cache=true")),
    ):
        status, content_type, text = _fetch(base_url + path)
        _require(status == 200, f"{path}: expected HTTP 200")
        _require(content_type == "text/plain", f"{path}: expected text/plain")
        for marker in markers:
            _require(marker in text, f"{path}: missing expected marker {marker}")

        if path == "/llms.txt":
            match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
            _require(match is not None, "/llms.txt: missing JSON example")
            example = json.loads(match.group(1))
            _require(
                example["params"]["arguments"]["url"]
                == "https://" + "example.com/",
                "/llms.txt: example target is not the intended plain URL",
            )
        print(f"OK  {path}")

    status, content_type, text = _fetch(
        base_url + "/mcp",
        {"jsonrpc": "2.0", "id": 901, "method": "tools/list"},
    )
    _require(status == 200, "tools/list: expected HTTP 200")
    _require(content_type == "application/json", "tools/list: expected application/json")
    rpc = json.loads(text)
    _require(isinstance(rpc, dict), "tools/list: expected JSON object")
    _require(rpc.get("jsonrpc") == "2.0", "tools/list: invalid JSON-RPC version")
    _require(rpc.get("id") == 901, "tools/list: response ID mismatch")
    _require("error" not in rpc, "tools/list: received JSON-RPC error")
    result = rpc.get("result")
    _require(isinstance(result, dict), "tools/list: missing result object")
    tools = result.get("tools")
    _require(isinstance(tools, list), "tools/list: missing tool list")
    tool = next(
        (item for item in tools
         if isinstance(item, dict) and item.get("name") == "bintu_scrape_text"),
        None,
    )
    _require(tool is not None, "tools/list: bintu_scrape_text not advertised")
    schema = tool.get("inputSchema")
    _require(isinstance(schema, dict), "tools/list: missing input schema")
    _require(
        "url" in schema.get("properties", {}),
        "tools/list: missing URL input",
    )
    print("OK  public MCP tools/list")
