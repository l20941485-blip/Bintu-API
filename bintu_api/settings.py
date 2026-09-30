import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    api_key: str
    rapidapi_proxy_secret: str
    request_timeout_seconds: float = 10.0
    max_redirects: int = 5
    max_html_bytes: int = 1024 * 1024
    max_text_characters: int = 6000
    rate_limit_requests: int = 60
    rate_limit_window_seconds: int = 60
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
        )