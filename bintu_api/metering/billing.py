"""Pure billing-policy classification for Bintu usage events.

This module does not persist usage, calculate currency amounts, or alter the
existing Supabase RPC contract. It classifies a successful or failed
extraction into the billing unit and cache-credit state required by policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

BillingUnit = Literal["context_tokens", "chunk_tokens"]


@dataclass(frozen=True)
class BillingDecision:
    billable_units: int
    unit: BillingUnit
    cache_credit_applied: bool


def classify_usage(
    *,
    tokens: int,
    mode: str,
    cache_hit: bool,
    extraction_failed: bool = False,
    quality_rejected: bool = False,
) -> BillingDecision:
    """Classify usage without changing persistence or public response shape."""
    unit: BillingUnit = "chunk_tokens" if mode == "chunk" else "context_tokens"
    billable_units = max(0, int(tokens))

    if extraction_failed or quality_rejected:
        return BillingDecision(
            billable_units=0,
            unit=unit,
            cache_credit_applied=False,
        )

    return BillingDecision(
        billable_units=billable_units,
        unit=unit,
        cache_credit_applied=bool(cache_hit),
    )
