"""HTTP middleware for Bintu request processing.

This module owns cross-cutting request concerns such as metering and context tracking without performing extraction or HTML parsing.

Important boundaries, invariants, and compatibility notes are documented here so the module stays focused on its owned behavior without drifting into unrelated routing or storage concerns.
"""

import logging

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from bintu_api.metering.billing import classify_usage
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
            supabase = getattr(request.app.state, "supabase_client", None)

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

                cache_hit = (
                    response.headers.get("X-Cache-Hit", "").lower() == "true"
                )
                mode = (
                    response.headers.get("x-mode")
                    or request.headers.get("x-mode")
                    or "unspecified"
                )

                # Classify using the returned-token value before applying the
                # legacy cache-hit token rule. This preserves the commercial
                # billing signal while the existing RPC continues to bill a
                # cache hit as zero tokens.
                billing = classify_usage(
                    tokens=tokens,
                    mode=mode,
                    cache_hit=cache_hit,
                )

                if cache_hit:
                    tokens = 0

                await record_usage_event(
                    supabase,
                    UsageEvent(
                        identity=identity[0],
                        gateway=identity[1],
                        scrapes=1,
                        tokens=tokens,
                        mode=mode,
                        billing=billing,
                    ),
                )

        return response
