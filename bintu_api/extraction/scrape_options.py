"""Presentation and extraction options for the scrape service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ScrapeOptions:
    """Options that control caching, extraction, and output formatting."""

    include_nav: bool
    include_header: bool
    include_footer: bool
    render_js: bool
    links: Literal["inline", "footnotes", "false"] = "inline"
    skip_cache: bool = False
    persist: bool = True
    mode: str = "scrape"
    max_tokens: int = 6000
    footnote_url_policy: Literal["full", "truncated"] = "truncated"
    max_footnote_url_length: int = 100
    sections: list[str] | None = None
