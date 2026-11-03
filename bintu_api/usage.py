import hashlib
import logging

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from bintu_api.auth import has_valid_proxy_secret
from bintu_api.settings import Settings

logger = logging.getLogger("bintu_api.usage")

EXCLUDED_PATHS = {
    "/",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
}


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def resolve_metering_identity(
    request: Request,
    settings: Settings,
) -> tuple[str, str] | None:
    """Return (rapidapi_user, gateway), or None when no billable identity exists."""

    if has_valid_proxy_secret(request, settings):
        rapidapi_key = request.headers.get("X-RapidAPI-Key", "")

        identity = (
            f"rapidapi:{_hash(rapidapi_key)}"
            if rapidapi_key
            else "rapidapi:gateway"
        )
        return identity, "rapidapi"

    api_key = request.headers.get("X-API-Key", "")
    if api_key and api_key == settings.mcp_api_key:
        return f"mcpize:{_hash(api_key)}", "mcpize"

    user_id = request.headers.get("x-user-id", "").strip().lower()
    if user_id:
        return f"local:{user_id}", "local"

    # Do not classify a Supabase Bearer session as MCPize traffic.
    return None


def increment_usage(
    supabase,
    *,
    identity: str,
    gateway: str,
    scrapes: int = 1,
    tokens: int = 0,
    mode: str | None = None,
) -> None:
    try:
        supabase.rpc(
            "increment_developer_usage",
            {
                "p_rapidapi_user": identity,
                "p_gateway": gateway,
                "p_scrapes": scrapes,
                "p_tokens": tokens,
                "p_mode": mode,
            },
        ).execute()
    except Exception:
        logger.exception(
            "supabase_usage_increment_failed",
            extra={
                "rapidapi_user": identity,
                "gateway": gateway,
                "scrapes": scrapes,
                "tokens": tokens,
                "mode": mode,
            },
        )


class UsageMeteringMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        should_meter = (
            request.method != "OPTIONS"
            and request.url.path not in EXCLUDED_PATHS
            and 200 <= response.status_code < 400
        )

        if should_meter:
            settings: Settings = request.app.state.settings
            identity = resolve_metering_identity(request, settings)

            if identity is not None:
                supabase = request.app.state.supabase_client

                if supabase is not None:
                    token_header = response.headers.get("x-token-usage", "0")

                    try:
                        tokens = int(token_header)
                    except ValueError:
                        tokens = 0

                    increment_usage(
                        supabase,
                        identity=identity[0],
                        gateway=identity[1],
                        scrapes=1,
                        tokens=tokens,
                        mode=request.headers.get("x-mode"),
                    )

        return response