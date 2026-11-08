"""Deprecated import path; retained for backward compatibility."""

from bintu_api.errors.http_errors import (
    UpstreamErrorSpec,
    resolve_upstream_error,
    translate_upstream_error,
)

__all__ = [
    "UpstreamErrorSpec",
    "resolve_upstream_error",
    "translate_upstream_error",
]
