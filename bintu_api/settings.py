import logging
import os
from dataclasses import dataclass
from typing import ClassVar

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
# RFC 9309 Compliance Configuration
    robots_mode: str = "enforce"  # enforce | warn | off
    robots_cache_ttl_seconds: int = 3600  # 1 hour cache TTL
    bot_info_url: str = ""  # Optional: e.g. https://bintu-api.example.com/bot-info
    contact_email: str = ""  # Optional: e.g. ops@example.com
    render_js_enabled: bool = False
    # REQUIRE_AUTH=true forbids the open-dev early return in verify_api_access:
    # WARNING: Enabling JavaScript rendering boots Playwright/Chromium
    # (2-4s startup + ongoing RAM). Only enable on paid/infra plans that
    # cover the latency and resource cost. Do not enable on free-tier.
    if render_js_enabled:
        logger.warning(
            "RENDER_JS_ENABLED is enabled - JavaScript rendering "
            "will boot Playwright/Chromium on every fetch. This incurs "
            "2-4s startup latency and ongoing RAM costs. "
            "Only enable on paid infrastructure plans."
        )
    # if both secrets are empty the service answers 500 auth_misconfiguration
    # instead of accepting unauthenticated traffic. Read in from_env (not as a
    # field default) so the value resolves per-app-creation like
    # render_js_enabled, keeping tests that patch os.environ deterministic.
    require_auth: bool = False
    service_title: str = "Bintu Data Extraction API"
    service_version: str = "1.1.0"
    # Comma-separated extra browser origins allowed to send credentialed
    # cross-origin requests. The MCPize gateway origin below is always allowed;
    # this setting exists so operators can add their own dashboards without a
    # code change. A wildcard-plus-credentials CORS policy would let any web
    # page act on a visitor's behalf, so the list is explicit (C3).
    cors_allowed_origins: str = ""
    # Comma-separated extra TCP ports the fetcher may connect to, in addition
    # to the default ports 80/443. Any other explicit port is rejected at
    # parse time so the service cannot be used as a public host/port probe
    # (S8). Override with ALLOWED_PORTS.
    allowed_ports: str = ""
    service_description: str = (
        "Extract readable text from public HTML pages. JavaScript rendering is "
        "disabled unless explicitly enabled. Responses are bounded, requests are "
        "rate-limited, and outbound connections are validated against public IP addresses."
    )

    # Origins always permitted via CORS: the MCPize gateway that fronts /mcp.
    CORS_GATEWAY_ORIGINS: ClassVar[tuple[str, ...]] = ("https://bintu-web-reader.mcpize.run",)

    def cors_origin_allowlist(self) -> tuple[str, ...]:
        """Origins allowed to make credentialed cross-origin requests."""
        extras = tuple(
            origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()
        )
        return self.CORS_GATEWAY_ORIGINS + extras

    def allowed_port_set(self) -> frozenset[int]:
        """TCP ports the fetcher may connect to: 80/443 plus ALLOWED_PORTS."""
        ports = {80, 443}
        for raw in self.allowed_ports.split(","):
            raw = raw.strip()
            if not raw:
                continue
            try:
                port = int(raw)
            except ValueError:
                logger.warning("invalid_allowed_port value=%r ignored", raw)
                continue
            if 1 <= port <= 65535:
                ports.add(port)
            else:
                logger.warning("out_of_range_allowed_port value=%r ignored", raw)
        return frozenset(ports)

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
            cors_allowed_origins=os.getenv("CORS_ALLOWED_ORIGINS", "").strip(),
            allowed_ports=os.getenv("ALLOWED_PORTS", "").strip(),
        )
