"""Health, gateway, and version endpoints for the Bintu API.

This module owns the public liveness, gateway-check, and build-metadata
routes. It performs no extraction, caching, or metering work.

Important boundaries, invariants, or compatibility notes:
- These routes are public and unauthenticated.
- Response shapes must remain identical to the legacy routes.py versions.
"""

import os

from fastapi import APIRouter, Request

from bintu_api.api.schemas import (
    GatewayResponse,
    HealthResponse,
    VersionResponse,
)
from bintu_api.settings import Settings

router = APIRouter(tags=["Health"])


@router.get("/", response_model=GatewayResponse)
def gateway_check(request: Request) -> GatewayResponse:
    settings = request.app.state.settings
    return GatewayResponse(
        status="ok",
        service=settings.service_title,
        docs="/docs",
    )


@router.get("/healthz", response_model=HealthResponse, include_in_schema=False)
def health_check(request: Request) -> HealthResponse:
    """Return liveness and non-secret deployed-build metadata."""
    settings: Settings = request.app.state.settings
    commit = os.getenv("RENDER_GIT_COMMIT", "").strip() or None
    environment = os.getenv("RENDER_SERVICE_NAME", "").strip() or None
    return HealthResponse(
        status="ok",
        version=settings.service_version,
        commit=commit,
        environment=environment,
    )


@router.get("/version", response_model=VersionResponse)
def version_info(request: Request) -> VersionResponse:
    settings: Settings = request.app.state.settings
    return VersionResponse(
        service=settings.service_title,
        version=settings.service_version,
        max_html_bytes=settings.max_html_bytes,
        max_redirects=settings.max_redirects,
        max_text_characters=settings.max_text_characters,
        rate_limit_requests=settings.rate_limit_requests,
        rate_limit_window_seconds=settings.rate_limit_window_seconds,
        cache_ttl_seconds=settings.cache_ttl_seconds,
    )
