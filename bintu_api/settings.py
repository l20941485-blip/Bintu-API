import logging
import os
from dataclasses import dataclass

logger = logging.getLogger("bintu_api.settings")

DEFAULT_CACHE_TTL_SECONDS = 300


def _bool_env(name: str, default: bool = False) -> bool:
    """Read a boolean environment flag; only an explicit true enables it.

    Anything else (empty, typo, "1", "yes") stays disabled so a mis-set
    value cannot accidentally boot Chromium on free-tier infra.
    """
    return os.getenv(name, "").strip().lower() == "true"


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
    # Optional second key accepted ONLY on the MCP surfaces (/mcp, /mcp/tools*).
    # Exists so connectors that store a static X-API-Key header (e.g. Claude
    # custom connectors) get a shareable, independently rotatable credential
    # that can never unlock the REST routes or /metrics.
    mcp_api_key: str = ""
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    request_timeout_seconds: float = 10.0
    max_redirects: int = 5
    max_html_bytes: int = 1024 * 1024
    max_text_characters: int = 6000
    rate_limit_requests: int = 60
    rate_limit_window_seconds: int = 60
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS
    redis_url: str = ""
    # Canonical upgrade URL embedded in 401 -32001 data so agents print a
    # clickable subscribe link in-chat. Override with BINTU_UPGRADE_URL.
    # No tier caps are enforced in code; dashboards own quota.
    upgrade_url: str = "https://mcpize.com"
    # JavaScript rendering boots Playwright/Chromium (2-4s + RAM). Off by
    # default on free infra; set RENDER_JS_ENABLED=true only on paid plans
    # where the latency and quota cost are covered. RapidAPI does not send
    # plan tier in headers, so per-plan gating is not enforceable here.
    render_js_enabled: bool = False
    # REQUIRE_AUTH=true forbids the open-dev early return in verify_api_access:
    # if both secrets are empty the service answers 500 auth_misconfiguration
    # instead of accepting unauthenticated traffic. Read in from_env (not as a
    # field default) so the value resolves per-app-creation like
    # render_js_enabled, keeping tests that patch os.environ deterministic.
    require_auth: bool = False
    service_title: str = "Bintu Data Extraction API"
    service_version: str = "1.0.0"
    service_description: str = (
        "Extract readable text from public HTML pages. JavaScript rendering is "
        "disabled unless explicitly enabled. Responses are bounded, requests are "
        "rate-limited, and outbound connections are validated against public IP addresses."
    )

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            api_key=os.getenv("API_KEY", "").strip(),
            rapidapi_proxy_secret=os.getenv("RAPIDAPI_PROXY_SECRET", "").strip(),
            mcp_api_key=os.getenv("MCP_API_KEY", "").strip(),
            supabase_url=os.getenv("SUPABASE_URL", "").strip().rstrip("/"),
            supabase_anon_key=os.getenv("SUPABASE_ANON_KEY", "").strip(),
            supabase_service_role_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip(),
            cache_ttl_seconds=_bounded_int_env(
                "CACHE_TTL_SECONDS", DEFAULT_CACHE_TTL_SECONDS, minimum=0, maximum=86400
            ),
            redis_url=os.getenv("REDIS_URL", "").strip(),
            upgrade_url=os.getenv("BINTU_UPGRADE_URL", "https://mcpize.com").strip()
            or "https://mcpize.com",
            render_js_enabled=_bool_env("RENDER_JS_ENABLED", default=False),
            require_auth=_bool_env("REQUIRE_AUTH", default=False),
        )
