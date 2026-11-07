"""Tool validation and invocation helpers for Bintu MCP.

This module owns argument normalization and dispatch logic without importing storage or network concerns.

Important boundaries, invariants, and compatibility notes are documented here so the module stays focused on its owned behavior without drifting into unrelated routing or storage concerns.
"""

import logging
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    model_validator,
)

from bintu_api.context import normalize_mode

logger = logging.getLogger("bintu_api.mcp")


class ToolCallRequest(BaseModel):
    name: str
    arguments: dict[str, Any]


class ToolArguments(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
    )

    url: str
    render_js: bool = False
    links: Literal["inline", "footnotes", "false"] = "inline"
    footnote_url_policy: Literal["full", "truncated"] = "truncated"
    max_footnote_url_length: StrictInt = Field(default=100, gt=0)
    mode: str = "scrape"
    max_tokens: int = Field(
        default=6000,
        ge=100,
        le=50000,
    )
    cache: bool = True
    persist: bool = True
    sections: str | list[str] | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_aliases(cls, data: Any) -> Any:
        """Normalize aliases while preserving canonical argument priority."""
        if not isinstance(data, dict):
            return data

        normalized = dict(data)

        if "mode" in normalized:
            normalized["mode"] = normalize_mode(normalized["mode"])

        if "chunk_token_budget" in normalized:
            if "max_tokens" in normalized:
                logger.warning(
                    "mcp_alias_conflict canonical=max_tokens wins over "
                    "chunk_token_budget"
                )
                normalized.pop("chunk_token_budget")
            else:
                normalized["max_tokens"] = normalized.pop(
                    "chunk_token_budget"
                )

        max_tokens = normalized.get("max_tokens", 6000)
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int):
            raise ValueError("max_tokens must be an integer")

        return normalized

    @model_validator(mode="after")
    def _validate_sections(self) -> "ToolArguments":
        if self.sections is None:
            return self

        if isinstance(self.sections, str):
            raw_selectors = self.sections.split("\n")
        elif isinstance(self.sections, list):
            raw_selectors = self.sections
        else:
            raise ValueError(
                "sections must be a string or an array of strings."
            )

        if any(not isinstance(selector, str) for selector in raw_selectors):
            raise ValueError("sections must contain only strings.")

        if any(not selector.strip() for selector in raw_selectors):
            raise ValueError(
                "sections cannot contain empty or whitespace-only selectors."
            )

        selectors = [selector.strip() for selector in raw_selectors]

        if any(len(selector) > 200 for selector in selectors):
            raise ValueError(
                "Each section selector must be 200 characters or fewer."
            )

        self.sections = selectors
        return self