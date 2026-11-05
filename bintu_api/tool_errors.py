from dataclasses import dataclass


@dataclass(frozen=True)
class ToolError:
    code: str
    message: str
    hint: str | None = None
    retryable: bool = False
    retry_with: str | None = None
