"""Command-line interface for running and inspecting the Bintu API service."""

from __future__ import annotations

import argparse
import json
import sys

import uvicorn

from bintu_api.settings import Settings


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bintu",
        description="Bintu Data Extraction API server and configuration CLI.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser(
        "serve",
        help="Run the Bintu FastAPI server.",
    )
    serve_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind host address (default: 127.0.0.1).",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Bind TCP port (default: 8000).",
    )
    serve_parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for local development.",
    )

    subparsers.add_parser(
        "check-config",
        help="Print non-secret effective configuration summary.",
    )
    return parser


def _config_summary(settings: Settings) -> dict[str, object]:
    return {
        "service_title": settings.service_title,
        "service_version": settings.service_version,
        "require_auth": settings.require_auth,
        "has_api_key": bool(settings.api_key),
        "has_mcp_api_key": bool(settings.mcp_api_key),
        "has_rapidapi_proxy_secret": bool(settings.rapidapi_proxy_secret),
        "has_supabase_url": bool(settings.supabase_url),
        "has_supabase_anon_key": bool(settings.supabase_anon_key),
        "has_supabase_service_role_key": bool(settings.supabase_service_role_key),
        "oauth_resource_url": settings.oauth_resource_url,
        "oauth_authorization_servers": [
            item.strip()
            for item in settings.oauth_authorization_servers.split(",")
            if item.strip()
        ],
        "render_js_enabled": settings.render_js_enabled,
        "robots_mode": settings.robots_mode,
        "cache_ttl_seconds": settings.cache_ttl_seconds,
    }


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "check-config":
        settings = Settings.from_env()
        print(json.dumps(_config_summary(settings), indent=2))
        return 0

    if args.command == "serve":
        uvicorn.run(
            "main:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
        )
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
