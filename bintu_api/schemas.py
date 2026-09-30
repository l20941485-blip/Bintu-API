from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str


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
    text: str