"""Transport helpers for modern MCP requests.

Not yet connected to the public endpoint.
This module does not advertise protocol support.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping
from typing import Any


PROTOCOL_VERSION_META_KEY = "io.modelcontextprotocol/protocolVersion"
HEADER_MISMATCH = -32020

_NAME_FIELDS = {
    "tools/call": "name",
    "prompts/get": "name",
    "resources/read": "uri",
}


class HeaderMismatch(ValueError):
    """A required HTTP header is missing, malformed, or inconsistent."""

    code = HEADER_MISMATCH
    status_code = 400


def _plain_header_is_safe(value: str) -> bool:
    return (
        bool(value)
        and value == value.strip()
        and all(
            char == "\t" or 0x20 <= ord(char) <= 0x7E
            for char in value
        )
    )


def decode_name_header(value: str) -> str:
    """Decode a plain or sentinel-encoded Mcp-Name value."""
    if not _plain_header_is_safe(value):
        raise HeaderMismatch("Malformed Mcp-Name header.")

    if value.startswith("=?base64?") and value.endswith("?="):
        encoded = value[len("=?base64?"):-2]
        try:
            return base64.b64decode(
                encoded, validate=True
            ).decode("utf-8", errors="strict")
        except (binascii.Error, UnicodeDecodeError, ValueError) as error:
            raise HeaderMismatch(
                "Malformed encoded Mcp-Name header."
            ) from error

    return value


def validate_mirrored_headers(
    headers: Mapping[str, str],
    payload: dict[str, Any],
) -> None:
    """Validate standard mirrored headers for an already-modern request.

    This does not select the protocol era, validate all request metadata,
    check version support, or validate custom Mcp-Param-* headers.
    """
    normalized = {name.lower(): value for name, value in headers.items()}

    params = payload.get("params")
    if not isinstance(params, dict):
        raise HeaderMismatch("Missing modern request metadata.")

    metadata = params.get("_meta")
    if not isinstance(metadata, dict):
        raise HeaderMismatch("Missing modern request metadata.")

    version = metadata.get(PROTOCOL_VERSION_META_KEY)
    declared_version = normalized.get("mcp-protocol-version")

    if (
        not isinstance(version, str)
        or not version
        or not isinstance(declared_version, str)
        or not _plain_header_is_safe(declared_version)
        or declared_version != version
    ):
        raise HeaderMismatch(
            "MCP-Protocol-Version header does not match request metadata."
        )

    method = payload.get("method")
    declared_method = normalized.get("mcp-method")

    if (
        not isinstance(method, str)
        or not method
        or not isinstance(declared_method, str)
        or not _plain_header_is_safe(declared_method)
        or declared_method != method
    ):
        raise HeaderMismatch(
            "Mcp-Method header does not match request method."
        )

    name_field = _NAME_FIELDS.get(method)
    if name_field is None:
        return

    body_name = params.get(name_field)
    declared_name = normalized.get("mcp-name")

    if not isinstance(body_name, str) or not isinstance(declared_name, str):
        raise HeaderMismatch("Missing named-operation routing value.")

    if decode_name_header(declared_name) != body_name:
        raise HeaderMismatch(
            "Mcp-Name header does not match request parameters."
        )