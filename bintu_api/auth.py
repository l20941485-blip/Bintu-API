import hmac
import json
import logging
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request as URLRequest, urlopen

from fastapi import HTTPException
from starlette.requests import Request

from bintu_api.settings import Settings


logger = logging.getLogger("bintu_api.auth")


def _secret_matches(provided: str, expected: str) -> bool:
    return bool(expected) and hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


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


def verify_supabase_user(request: Request, settings: Settings) -> str:
    authorization = request.headers.get("Authorization", "")
    scheme, separator, token = authorization.partition(" ")
    token = token.strip()
    invalid_token = (
        not token
        or len(token) > 8192
        or not token.isascii()
        or any(ord(character) < 33 or ord(character) > 126 for character in token)
    )
    if not separator or scheme.lower() != "bearer" or invalid_token:
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_session", "message": "A valid sign-in session is required."},
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not settings.supabase_url or not settings.supabase_anon_key:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "mobile_auth_not_configured",
                "message": "Mobile sign-in is not configured on this service.",
            },
        )

    try:
        parsed_url = urlsplit(settings.supabase_url)
    except ValueError as error:
        logger.error("invalid_supabase_url_configuration")
        raise HTTPException(
            status_code=503,
            detail={"code": "mobile_auth_not_configured", "message": "Mobile sign-in is unavailable."},
        ) from error
    local_http = parsed_url.scheme == "http" and parsed_url.hostname in {"localhost", "127.0.0.1"}
    invalid_url = (
        not parsed_url.hostname
        or (parsed_url.scheme != "https" and not local_http)
        or parsed_url.path not in {"", "/"}
        or bool(parsed_url.query or parsed_url.fragment or parsed_url.username or parsed_url.password)
    )
    if invalid_url:
        logger.error("invalid_supabase_url_configuration")
        raise HTTPException(
            status_code=503,
            detail={"code": "mobile_auth_not_configured", "message": "Mobile sign-in is unavailable."},
        )
    if "\r" in settings.supabase_anon_key or "\n" in settings.supabase_anon_key:
        logger.error("invalid_supabase_anon_key_configuration")
        raise HTTPException(
            status_code=503,
            detail={"code": "mobile_auth_not_configured", "message": "Mobile sign-in is unavailable."},
        )

    try:
        auth_request = URLRequest(
            f"{settings.supabase_url}/auth/v1/user",
            headers={
                "apikey": settings.supabase_anon_key,
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        with urlopen(auth_request, timeout=5) as response:
            body = response.read(65537)
    except ValueError as error:
        logger.error("invalid_supabase_auth_configuration")
        raise HTTPException(
            status_code=503,
            detail={"code": "mobile_auth_not_configured", "message": "Mobile sign-in is unavailable."},
        ) from error
    except HTTPError as error:
        if error.code in {400, 401, 403}:
            raise HTTPException(
                status_code=401,
                detail={"code": "invalid_session", "message": "Your sign-in session is invalid or expired."},
                headers={"WWW-Authenticate": "Bearer"},
            ) from error
        logger.warning("supabase_auth_unavailable status=%d", error.code)
        raise HTTPException(
            status_code=503,
            detail={"code": "mobile_auth_unavailable", "message": "Sign-in verification is temporarily unavailable."},
        ) from error
    except (URLError, TimeoutError, OSError) as error:
        logger.warning("supabase_auth_unavailable error_type=%s", type(error).__name__)
        raise HTTPException(
            status_code=503,
            detail={"code": "mobile_auth_unavailable", "message": "Sign-in verification is temporarily unavailable."},
        ) from error

    if len(body) > 65536:
        logger.warning("supabase_auth_invalid_response reason=response_too_large")
        raise HTTPException(
            status_code=503,
            detail={"code": "mobile_auth_unavailable", "message": "Sign-in verification returned an invalid response."},
        )
    try:
        user = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        logger.warning("supabase_auth_invalid_response reason=invalid_json")
        raise HTTPException(
            status_code=503,
            detail={"code": "mobile_auth_unavailable", "message": "Sign-in verification returned an invalid response."},
        ) from error

    user_id = user.get("id") if isinstance(user, dict) else None
    if not isinstance(user_id, str) or not user_id:
        logger.warning("supabase_auth_invalid_response reason=missing_user_id")
        raise HTTPException(
            status_code=503,
            detail={"code": "mobile_auth_unavailable", "message": "Sign-in verification returned an invalid response."},
        )
    if not user.get("email_confirmed_at"):
        raise HTTPException(
            status_code=403,
            detail={"code": "email_not_verified", "message": "Verify your email address before using the app."},
        )
    return user_id


def rate_limit_identity(request: Request, settings: Settings) -> str:
    if has_valid_proxy_secret(request, settings):
        rapidapi_user = request.headers.get("X-RapidAPI-User")
        if rapidapi_user:
            return f"rapidapi:{rapidapi_user}"
    return request.client.host if request.client else "unknown"