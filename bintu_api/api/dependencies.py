"""Shared API dependencies and auth re-exports for Bintu route modules.

This module exists to give route modules a single import point for auth and
rate-limit helpers. It owns no business logic; it only re-exports the
canonical implementations from bintu_api.auth.

Important boundaries, invariants, or compatibility notes:
- Do not add extraction, caching, or metering logic here.
- Keep the re-export surface stable so route modules can migrate gradually.
"""

from bintu_api.auth import (
    api_key_scheme,
    bearer_scheme,
    has_valid_proxy_secret,
    rate_limit_identity,
    verify_api_access,
    verify_supabase_user,
)

__all__ = [
    "api_key_scheme",
    "bearer_scheme",
    "has_valid_proxy_secret",
    "rate_limit_identity",
    "verify_api_access",
    "verify_supabase_user",
]
