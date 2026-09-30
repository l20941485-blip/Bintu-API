import hmac

from fastapi import HTTPException
from starlette.requests import Request

from bintu_api.settings import Settings


def _secret_matches(provided: str, expected: str) -> bool:
    if not expected:
        return False
    provided_bytes = provided.encode("utf-8")
    expected_bytes = expected.encode("utf-8")
    # Python < 3.14 raises ValueError when lengths differ; keep that as a failed match.
    if len(provided_bytes) != len(expected_bytes):
        return False
    return hmac.compare_digest(provided_bytes, expected_bytes)


def has_valid_proxy_secret(request: Request, settings: Settings) -> bool:
    provided = request.headers.get("X-RapidAPI-Proxy-Secret", "")
    return _secret_matches(provided, settings.rapidapi_proxy_secret)


def verify_api_access(request: Request, settings: Settings) -> None:
    if not settings.api_key and not settings.rapidapi_proxy_secret:
        return

    api_key_valid = _secret_matches(request.headers.get("X-API-Key", ""), settings.api_key)
    if not api_key_valid and not has_valid_proxy_secret(request, settings):
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_api_key", "message": "A valid API key is required."},
            headers={"WWW-Authenticate": "ApiKey"},
        )


def rate_limit_identity(request: Request, settings: Settings) -> str:
    if has_valid_proxy_secret(request, settings):
        rapidapi_user = request.headers.get("X-RapidAPI-User")
        if rapidapi_user:
            return f"rapidapi:{rapidapi_user}"
    return request.client.host if request.client else "unknown"