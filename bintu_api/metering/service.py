"""Usage policy and event handling for Bintu metering.

This module owns usage intent, event scheduling, and the service boundary between request handling and Supabase persistence.

Important boundaries, invariants, and compatibility notes are documented here so the module stays focused on its owned behavior without drifting into unrelated routing or storage concerns.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Literal

from starlette.requests import Request

from bintu_api.integrations.supabase import DATABASE_TIMEOUT_SECONDS
from bintu_api.metering.supabase import (
    increment_developer_usage,
)
from bintu_api.metering.supabase import (
    increment_usage as increment_usage_in_supabase,
)

logger = logging.getLogger("bintu_api.metering")


@dataclass(frozen=True)
class UsageEvent:
    identity: str
    gateway: str | None = None
    scrapes: int = 1
    tokens: int = 0
    mode: str | None = None
    legacy_rpc: bool = False
    source: Literal["mcp", "rest", "reader"] = "mcp"


def queue_usage_event(request: Request, event: UsageEvent) -> None:
    request.state.bintu_usage_event = event


async def increment_usage(
    supabase,
    *,
    identity: str,
    gateway: str,
    scrapes: int = 1,
    tokens: int = 0,
    mode: str | None = None,
) -> None:
    await increment_usage_in_supabase(
        supabase,
        identity=identity,
        gateway=gateway,
        scrapes=scrapes,
        tokens=tokens,
        mode=mode,
    )


async def record_usage_event(supabase, event: UsageEvent) -> None:
    if not event.legacy_rpc:
        await increment_usage(
            supabase,
            identity=event.identity,
            gateway=event.gateway or "unknown",
            scrapes=event.scrapes,
            tokens=event.tokens,
            mode=event.mode,
        )
        return

    try:
        await asyncio.wait_for(
            increment_developer_usage(supabase, event.identity),
            timeout=DATABASE_TIMEOUT_SECONDS,
        )
    except Exception as error:
        logger_name = "bintu_api.reader" if event.source == "reader" else "bintu_api.scrape"
        logging.getLogger(logger_name).warning(
            "reader_usage_increment_failed" if event.source == "reader" else "supabase_usage_increment_failed",
            extra={"error_type": type(error).__name__},
        )
