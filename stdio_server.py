"""Stdio MCP entry point for Glama's managed source-build checker.

Reads one JSON-RPC message per line from stdin and writes one JSON-RPC
response per line to stdout. Reuses Bintu's existing Streamable HTTP
tool implementation without starting Uvicorn.
"""

import asyncio
import json
import sys
from types import SimpleNamespace

from starlette.requests import Request

from bintu_api.cache import TTLCache
from bintu_api.database import (
    close_supabase_client,
    create_supabase_client,
)
from bintu_api.mcp_streamable import (
    _initialize_result,
    _rpc_error,
    _rpc_result,
    _tools_call_result,
    _tools_list_result,
)
from bintu_api.rate_limit import create_rate_limiter
from bintu_api.settings import Settings


METHOD_NOT_FOUND = -32601


class MinimalApp:
    def __init__(self, settings: Settings):
        self.state = SimpleNamespace(
            settings=settings,
            rate_limiter=create_rate_limiter(settings),
            cache=TTLCache(settings.cache_ttl_seconds),
            supabase_client=None,
        )


async def make_request(app: MinimalApp) -> Request:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/mcp",
        "raw_path": b"/mcp",
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("127.0.0.1", 0),
        "server": ("127.0.0.1", 80),
        "app": app,
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)


async def handle_message(app: MinimalApp, message: dict) -> dict | None:
    request_id = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}

    if not isinstance(params, dict):
        params = {}

    if method == "initialize":
        return _initialize_result(app.state.settings, request_id, params)

    if method == "notifications/initialized":
        return None

    if method == "ping":
        return _rpc_result(request_id, {})

    if method == "tools/list":
        return _tools_list_result(request_id)

    if method == "tools/call":
        request = await make_request(app)
        return await _tools_call_result(
            request,
            app.state.settings,
            request_id,
            params,
        )

    if request_id is None:
        return None

    return _rpc_error(
        request_id,
        METHOD_NOT_FOUND,
        f"Method not found: {method}",
    )


async def run() -> None:
    settings = Settings.from_env()
    app = MinimalApp(settings)

    try:
        app.state.supabase_client = await create_supabase_client(settings)
    except Exception:
        app.state.supabase_client = None

    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)

    await loop.connect_read_pipe(lambda: protocol, sys.stdin.buffer)

    try:
        while True:
            line = await reader.readline()
            if not line:
                break

            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue

            if not isinstance(message, dict):
                continue

            response = await handle_message(app, message)

            if response is not None:
                sys.stdout.write(
                    json.dumps(response, separators=(",", ":")) + "\n"
                )
                sys.stdout.flush()
    finally:
        if app.state.supabase_client is not None:
            try:
                await close_supabase_client(app.state.supabase_client)
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(run())