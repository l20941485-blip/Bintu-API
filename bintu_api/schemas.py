from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str
    hint: str | None = None


class ErrorResponse(BaseModel):
    detail: ErrorDetail


class GatewayResponse(BaseModel):
    status: str
    service: str
    docs: str


class HealthResponse(BaseModel):
    status: str


class ScrapeTextResponse(BaseModel):
    url: str
    # Length is enforced by extract_text() against settings.max_text_characters;
    # duplicating the limit here as a pydantic constraint would turn a raised
    # limit into a response-serialization 500.
    text: str


class VersionResponse(BaseModel):
    service: str
    version: str
    max_html_bytes: int
    max_redirects: int
    max_text_characters: int
    rate_limit_requests: int
    rate_limit_window_seconds: int
    cache_ttl_seconds: int
