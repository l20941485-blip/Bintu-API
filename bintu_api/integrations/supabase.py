from typing import TYPE_CHECKING, Any, TypeAlias

from bintu_api.settings import Settings

if TYPE_CHECKING:
    from supabase import AsyncClient  # type: ignore[import-not-found,import-unresolved] # pyright: ignore[reportMissingImports]
else:
    AsyncClient: TypeAlias = Any


DATABASE_TIMEOUT_SECONDS = 2.0


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
