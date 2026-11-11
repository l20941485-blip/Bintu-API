"""Robots enforcement policy for outbound document retrieval.

This module owns the robots enforcement boundary. The low-level robots
protocol, parsing, caching, and decision logic remain in ``bintu_api.scraper.robots``.

The dependency parameters preserve the established patch seam in
``bintu_api.api.scrape_adapter`` during the modularization transition.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from fastapi import HTTPException

from bintu_api.common.robots import RobotsDecision
from bintu_api.settings import Settings

logger = logging.getLogger("bintu_api.scrape")


async def enforce_robots(
    url: str,
    settings: Settings,
    url_hash: str,
    *,
    robots_mode_fn: Callable[[Settings], str],
    robots_decision_fn: Callable[[str, Settings], Awaitable[RobotsDecision]],
) -> None:
    """Check robots.txt before any network fetch of the page.


    enforce: an explicit robots disallow blocks with 403. A robots.txt retrieval
    failure also blocks with 403, but is reported as ``robots_unreachable``.
    warn: log and continue. off: skipped inside robots_decision.
    The blocking check runs in a worker thread. URLs are never logged, only a hash.
    """
    mode = robots_mode_fn(settings)
    if mode == "off":
        return

    decision = await asyncio.to_thread(robots_decision_fn, url, settings)
    if decision.allowed:
        return

    logger.info(
        "robots_not_allowed url_hash=%s mode=%s unreachable=%s reason=%s",
        url_hash,
        mode,
        decision.unreachable,
        decision.reason,
    )

    if mode == "enforce":
        if decision.unreachable:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "robots_unreachable",
                    "message": (f"Fetching this page is not permitted: {decision.reason.rstrip('.')}."),
                    "hint": (
                        "The target's robots.txt could not be retrieved. "
                        "Access is denied while robots enforcement is enabled."
                    ),
                },
            )

        raise HTTPException(
            status_code=403,
            detail={
                "code": "blocked_by_robots",
                "message": (f"Fetching this page is not permitted: {decision.reason.rstrip('.')}."),
                "hint": ("Bintu respects robots.txt. The site owner controls this."),
            },
        )
