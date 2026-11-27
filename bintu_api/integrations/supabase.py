"""Integration boundaries for external Bintu services.

This module isolates upstream integration code so application logic does not directly couple to external service details.

Important boundaries, invariants, and compatibility notes are documented here so the module stays focused on its owned behavior without drifting into unrelated routing or storage concerns.
"""

import asyncio
from typing import TYPE_CHECKING, Any, TypeAlias

from bintu_api.settings import Settings

if TYPE_CHECKING:
    from supabase import AsyncClient  # type: ignore[import-not-found,import-unresolved] # pyright: ignore[reportMissingImports]
else:
    AsyncClient: TypeAlias = Any


import os


def _default_database_timeout_seconds() -> float:
    raw = os.getenv("SUPABASE_RPC_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return 15.0
    try:
        value = float(raw)
    except ValueError:
        return 15.0
    return value if value > 0 else 15.0


DATABASE_TIMEOUT_SECONDS = _default_database_timeout_seconds()


async def create_supabase_client(settings: Settings) -> AsyncClient | None:
    """Create a server-side client only when the private database key is configured."""
    if not settings.supabase_url or not settings.supabase_service_role_key:
        return None

    try:
        from supabase import create_async_client  # type: ignore[import-not-found,import-unresolved] # pyright: ignore[reportMissingImports]
    except ImportError as exc:
        raise RuntimeError(
            "supabase package is not installed. Install it with `pip install supabase==2.33.0`."
        ) from exc

    return await create_async_client(settings.supabase_url, settings.supabase_service_role_key)


async def close_supabase_client(client: AsyncClient) -> None:
    """Shut down a Supabase client using the installed SDK's supported API."""
    auth = getattr(client, "auth", None)
    sign_out = getattr(auth, "sign_out", None)

    if sign_out is None:
        return

    result = sign_out()

    if hasattr(result, "__await__"):
        await result


class SupabaseRpcTimeoutError(TimeoutError):
    """Raised when a Supabase RPC call exceeds its configured timeout."""


async def execute_supabase_rpc(
    client: Any,
    rpc_name: str,
    params: dict[str, Any],
    *,
    timeout_seconds: float = DATABASE_TIMEOUT_SECONDS,
) -> Any:
    """Execute a Supabase RPC with an explicit async timeout."""
    try:
        return await asyncio.wait_for(
            client.rpc(rpc_name, params).execute(),
            timeout=timeout_seconds,
        )
    except TimeoutError as exc:
        raise SupabaseRpcTimeoutError(
            f"Supabase RPC '{rpc_name}' timed out after {timeout_seconds}s"
        ) from exc
