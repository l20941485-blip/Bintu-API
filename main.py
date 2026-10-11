import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request

from bintu_api.auth import verify_api_access
from bintu_api.cache import TTLCache
from bintu_api.database import (
    DATABASE_TIMEOUT_SECONDS,
    close_supabase_client,
    create_supabase_client,
)
from bintu_api.mcp import router as mcp_router
from bintu_api.observability import RequestObservabilityMiddleware, metrics_response
from bintu_api.rate_limit import create_rate_limiter
from bintu_api.routes import router
from bintu_api.settings import Settings


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        try:
            application.state.supabase_client = await asyncio.wait_for(
                create_supabase_client(app_settings),
                timeout=DATABASE_TIMEOUT_SECONDS,
            )
        except Exception as error:
            logging.getLogger("bintu_api.database").warning(
                "supabase_client_initialization_failed error_type=%s", type(error).__name__
            )
            application.state.supabase_client = None
        try:
            yield
        finally:
            client = application.state.supabase_client
            if client is not None:
                try:
                    await asyncio.wait_for(
                        close_supabase_client(client),
                        timeout=DATABASE_TIMEOUT_SECONDS,
                    )
                except Exception as error:
                    logging.getLogger("bintu_api.database").warning(
                        "supabase_client_close_failed error_type=%s", type(error).__name__
                    )

    application = FastAPI(
        title=app_settings.service_title,
        description=app_settings.service_description,
        version=app_settings.service_version,
        license_info={"name": "MIT", "url": "https://opensource.org/licenses/MIT"},
        lifespan=lifespan,
    )
    application.state.settings = app_settings
    application.state.rate_limiter = create_rate_limiter(app_settings)
    application.state.cache = TTLCache(app_settings.cache_ttl_seconds)
    application.state.supabase_client = None
    application.add_middleware(RequestObservabilityMiddleware)
    application.include_router(router)
    application.include_router(mcp_router)

    @application.get("/metrics", include_in_schema=False)
    def metrics(request: Request):
        # Operational telemetry: require the same credentials as the API so the
        # endpoint cannot be used to enumerate traffic on a public hostname.
        verify_api_access(request, app_settings)
        return metrics_response()

    return application


app = create_app()
