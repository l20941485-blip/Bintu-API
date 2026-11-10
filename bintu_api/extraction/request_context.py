"""Request-scoped values required by the scrape service.

This value object prevents the scrape service from depending on FastAPI's
request object or its internal application-state structure.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScrapeRequestContext:
    """Values derived from an incoming scrape request."""

    settings: object
    database_client: object | None
    request_id: str | None
