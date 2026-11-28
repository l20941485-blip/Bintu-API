"""Aggregated HTTP routes for the Bintu API."""

from fastapi import APIRouter

from bintu_api.api.discovery import router as discovery_router
from bintu_api.api.routes.chunk import router as chunk_router
from bintu_api.api.routes.extract import router as extract_router
from bintu_api.api.routes.health import router as health_router
from bintu_api.api.routes.rag import router as rag_router

router = APIRouter()
router.include_router(discovery_router)
router.include_router(health_router)
router.include_router(extract_router)
router.include_router(chunk_router)
router.include_router(rag_router)

__all__ = ["router"]
