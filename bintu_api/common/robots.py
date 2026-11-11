"""Shared robots decision contract."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RobotsDecision:
    allowed: bool
    reason: str
    checked: bool = True
    matched_group: str = "none"
    unreachable: bool = False