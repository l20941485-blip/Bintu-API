import logging

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from bintu_api.metering.identity import resolve_metering_identity
from bintu_api.metering.service import UsageEvent, record_usage_event
from bintu_api.settings import Settings

logger = logging.getLogger("bintu_api.usage")


EXCLUDED_PATHS = {
    "/",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
}

METERED_PATHS = {
    "/mcp",
}


class UsageMeteringMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        queued_event = getattr(request.state, "bintu_usage_event", None)
        if isinstance(queued_event, UsageEvent):
            supabase = getattr(request.app.state, "supabase_client", None)
            if supabase is not None:
                await record_usage_event(supabase, queued_event)
            return response

        should_meter = (
            request.method == "POST"
            and request.url.path in METERED_PATHS
            and 200 <= response.status_code < 400
            and response.headers.get("x-token-usage") is not None
        )

        if should_meter:
            settings: Settings = request.app.state.settings
            identity = resolve_metering_identity(request, settings)
            supabase = request.app.state.supabase_client

            logger.info(
                "usage_metering_decision path=%s status=%s identity=%s gateway=%s supabase_client_present=%s",
                request.url.path,
                response.status_code,
                identity[0] if identity else None,
                identity[1] if identity else None,
                supabase is not None,
            )

            if identity is not None and supabase is not None:
                token_header = response.headers.get("x-token-usage", "0")

                try:
                    tokens = int(token_header)
                except ValueError:
                    tokens = 0

                await record_usage_event(
                    supabase,
                    UsageEvent(
                        identity=identity[0],
                        gateway=identity[1],
                        scrapes=1,
                        tokens=tokens,
                        mode=(
                            response.headers.get("x-mode")
                            or request.headers.get("x-mode")
                            or "unspecified"
                        ),
                    ),
                )

        return response
