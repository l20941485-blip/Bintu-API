"""Package exports and compatibility shims for Bintu.

This module makes the public Bintu package surface explicit and keeps legacy imports stable while the modular architecture is being adopted.

Important boundaries, invariants, and compatibility notes are documented here so the module stays focused on its owned behavior without drifting into unrelated routing or storage concerns.
"""

from bintu_api.metering.identity import resolve_metering_identity
from bintu_api.metering.service import UsageEvent, increment_usage, record_usage_event

__all__ = [
    "UsageEvent",
    "increment_usage",
    "record_usage_event",
    "resolve_metering_identity",
]
