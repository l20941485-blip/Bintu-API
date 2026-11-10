"""Supabase persistence for metering events in Bintu.

This module performs the exact RPC calls required by the metering contract and keeps persistence logic separate from request identity and policy code.

Important boundaries, invariants, and compatibility notes are documented here so the module stays focused on its owned behavior without drifting into unrelated routing or storage concerns.
"""

import logging
from typing import Any

logger = logging.getLogger("bintu_api.usage")


async def increment_usage(
    supabase: Any,
    *,
    identity: str,
    gateway: str,
    scrapes: int = 1,
    tokens: int = 0,
    mode: str | None = None,
) -> None:
    try:
        response = await supabase.rpc(
            "increment_developer_usage",
            {
                "p_rapidapi_user": identity,
                "p_gateway": gateway,
                "p_scrapes": scrapes,
                "p_tokens": tokens,
                "p_mode": mode,
            },
        ).execute()

        logger.info(
            "supabase_usage_increment_completed response=%s",
            response,
        )
    except Exception:
        logger.exception(
            "supabase_usage_increment_failed",
            extra={
                "rapidapi_user": identity,
                "gateway": gateway,
                "scrapes": scrapes,
                "tokens": tokens,
                "mode": mode,
            },
        )


async def increment_developer_usage(supabase: Any, rapidapi_user: str) -> None:
    await supabase.rpc(
        "increment_developer_usage",
        {"p_rapidapi_user": rapidapi_user},
    ).execute()


async def increment_token_usage(
    supabase: Any,
    rapidapi_user: str,
    tokens: int = 1,
    mode: str = "scrape",
) -> None:
    await supabase.rpc(
        "increment_developer_usage",
        {
            "p_rapidapi_user": rapidapi_user,
            "p_tokens": max(0, int(tokens)),
            "p_mode": mode,
        },
    ).execute()
