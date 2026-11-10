"""Deprecated import path; retained for backward compatibility."""

from bintu_api.render.proxy_protocol import (
    MAX_CONNECT_HEAD_BYTES,
    ConnectRequestHead,
    ConnectTarget,
    ProxyRequestRejected,
    parse_connect_authority,
    parse_connect_request_head,
)

__all__ = [
    "MAX_CONNECT_HEAD_BYTES",
    "ConnectRequestHead",
    "ConnectTarget",
    "ProxyRequestRejected",
    "parse_connect_authority",
    "parse_connect_request_head",
]
