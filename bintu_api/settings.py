import logging
import os
from dataclasses import dataclass

logger = logging.getLogger("bintu_api.settings")

DEFAULT_CACHE_TTL_SECONDS = 300


def _bounded_int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    """Read an integer environment override, falling back to the default.

    ``create_app()`` runs at import time, so an unparseable or nonsensical value
    would crash-loop the container instead of serving traffic; a bad override
    therefore degrades to the default with a warning rather than raising.
    """
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("invalid_env_value name=%s value=%r using_default=%d", name, raw, default)
        return default
    if not minimum <= value <= maximum:
        logger.warning(
            "out_of_range_env_value name=%s value=%d allowed=%d..%d using_default=%d",
            name,
            value,
            minimum,
            maximum,
            default,
        )
        return default
    return value


@dataclass(frozen=True)
class Settings:
    api_key: str
    rapidapi_proxy_secret: str
    supabase_url: str = ""
    supabase_anon_key: str = ""
    request_timeout_seconds: float = 10.0
    max_redirects: int = 5
    max_html_bytes: int = 1024 * 1024
    max_text_characters: int = 6000
    rate_limit_requests: int = 60
    rate_limit_window_seconds: int = 60
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS
    redis_url: str = ""
    service_title: str = "Bintu Data Extraction API"
    service_version: str = "1.0.0"
    service_description: str = (
        "Extract readable text from public HTML pages. Responses are bounded, "
        "requests are rate-limited, and outbound connections are pinned to validated public IPs."
    )

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            api_key=os.getenv("API_KEY", "").strip(),
            rapidapi_proxy_secret=os.getenv("RAPIDAPI_PROXY_SECRET", "").strip(),
            supabase_url=os.getenv("SUPABASE_URL", "").strip().rstrip("/"),
            supabase_anon_key=os.getenv("SUPABASE_ANON_KEY", "").strip(),
            cache_ttl_seconds=_bounded_int_env(
                "CACHE_TTL_SECONDS", DEFAULT_CACHE_TTL_SECONDS, minimum=0, maximum=86400
            ),
            redis_url=os.getenv("REDIS_URL", "").strip(),
        )
