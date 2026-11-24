"""Pure billing-policy classification for Bintu usage events.

This module does not persist usage, calculate currency amounts, or alter the
existing Supabase RPC contract. It classifies a successful or failed
extraction into the billing unit and cache-credit state required by policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

BillingUnit = Literal["context_tokens", "chunk_tokens"]


_RATE_PER_MILLION_USD: dict[tuple[BillingUnit, bool], float] = {
    ("context_tokens", False): 2.00,
    ("context_tokens", True): 0.40,
    ("chunk_tokens", False): 0.25,
    ("chunk_tokens", True): 0.25,
}


def estimate_cost_usd(
    *,
    billable_units: int,
    unit: BillingUnit,
    cache_credit_applied: bool,
) -> float:
    """Estimate cost in USD from billable token units and billing policy."""
    units = max(0, int(billable_units))
    if units == 0:
        return 0.0
    rate = _RATE_PER_MILLION_USD[(unit, bool(cache_credit_applied))]
    return round((units * rate) / 1_000_000, 6)


@dataclass(frozen=True)
class BillingDecision:
    billable_units: int
    unit: BillingUnit
    cache_credit_applied: bool
    estimated_cost_usd: float = 0.0


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
            estimated_cost_usd=0.0,
        )

    credit_applied = bool(cache_hit)
    return BillingDecision(
        billable_units=billable_units,
        unit=unit,
        cache_credit_applied=credit_applied,
        estimated_cost_usd=estimate_cost_usd(
            billable_units=billable_units,
            unit=unit,
            cache_credit_applied=credit_applied,
        ),
    )
