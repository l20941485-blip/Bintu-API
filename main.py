import logging
import sys

from fastapi import FastAPI, Request

from bintu_api.auth import verify_api_access
from bintu_api.cache import TTLCache
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
    application = FastAPI(
        title=app_settings.service_title,
        description=app_settings.service_description,
        version=app_settings.service_version,
        license_info={"name": "MIT", "url": "https://opensource.org/licenses/MIT"},
    )
    application.state.settings = app_settings
    application.state.rate_limiter = create_rate_limiter(app_settings)
    application.state.cache = TTLCache(app_settings.cache_ttl_seconds)
    application.add_middleware(RequestObservabilityMiddleware)
    application.include_router(router)

    @application.get("/metrics", include_in_schema=False)
    def metrics(request: Request):
        # Operational telemetry: require the same credentials as the API so the
        # endpoint cannot be used to enumerate traffic on a public hostname.
        verify_api_access(request, app_settings)
        return metrics_response()

    return application


app = create_app()
