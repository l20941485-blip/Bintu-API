import hashlib

from starlette.requests import Request

from bintu_api.auth import has_valid_proxy_secret
from bintu_api.settings import Settings


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def resolve_metering_identity(
    request: Request,
    settings: Settings,
) -> tuple[str, str] | None:
    """Return (rapidapi_user, gateway), or None when no billable identity exists."""
    if has_valid_proxy_secret(request, settings):
        rapidapi_key = request.headers.get("X-RapidAPI-Key", "")

        identity = (
            f"rapidapi:{_hash(rapidapi_key)}"
            if rapidapi_key
            else "rapidapi:gateway"
        )
        return identity, "rapidapi"

    api_key = request.headers.get("X-API-Key", "")
    if api_key and api_key == settings.mcp_api_key:
        return f"mcpize:{_hash(api_key)}", "mcpize"

    user_id = request.headers.get("x-user-id", "").strip().lower()
    if user_id:
        return f"local:{user_id}", "local"

    return None
