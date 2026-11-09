"""Aggregated HTTP routes for the Bintu API."""

from fastapi import APIRouter

from bintu_api.api.routes.chunk import router as chunk_router
from bintu_api.api.routes.extract import router as extract_router
from bintu_api.api.routes.health import router as health_router

router = APIRouter()
router.include_router(health_router)
router.include_router(extract_router)
router.include_router(chunk_router)

__all__ = ["router"]
