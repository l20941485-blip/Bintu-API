"""Legacy usage compatibility surface for Bintu.

This module preserves public imports while the metering implementation is gradually moved into the dedicated metering package.

Important boundaries, invariants, and compatibility notes are documented here so the module stays focused on its owned behavior without drifting into unrelated routing or storage concerns.
"""

from bintu_api.metering.identity import _hash, resolve_metering_identity
from bintu_api.metering.service import increment_usage
from bintu_api.middleware.usage import (
    EXCLUDED_PATHS,
    METERED_PATHS,
    UsageMeteringMiddleware,
)

__all__ = [
    "EXCLUDED_PATHS",
    "METERED_PATHS",
    "UsageMeteringMiddleware",
    "_hash",
    "increment_usage",
    "resolve_metering_identity",
]
