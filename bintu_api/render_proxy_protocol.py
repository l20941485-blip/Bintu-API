"""Strict CONNECT authority parsing.

Syntax validation only: no DNS resolution or destination authorization.
Not a complete HTTP proxy parser. S9 remains open.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass


class ProxyRequestRejected(ValueError):
    pass


@dataclass(frozen=True)
class ConnectTarget:
    host: str
    port: int


def parse_connect_authority(authority: str) -> ConnectTarget:
    """Parse explicit host:port or [IPv6]:port without network access."""
    if (
        not authority
        or len(authority) > 512
        or not authority.isascii()
        or any(ord(char) <= 32 or ord(char) == 127 for char in authority)
    ):
        raise ProxyRequestRejected("Invalid CONNECT authority")

    if authority.startswith("["):
        match = re.fullmatch(r"\[([0-9A-Fa-f:.]+)\]:([0-9]{1,5})", authority)
        if match is None:
            raise ProxyRequestRejected("Invalid bracketed CONNECT target")
        try:
            host = str(ipaddress.IPv6Address(match.group(1)))
        except ValueError as error:
            raise ProxyRequestRejected("Invalid IPv6 target") from error
    else:
        match = re.fullmatch(r"([A-Za-z0-9.-]+):([0-9]{1,5})", authority)
        if match is None:
            raise ProxyRequestRejected("CONNECT requires host:port")

        host = match.group(1).lower()
        if len(host) > 253:
            raise ProxyRequestRejected("Hostname too long")

        labels = host.split(".")
        if any(
            re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            is None
            for label in labels
        ):
            raise ProxyRequestRejected("Invalid hostname")

    port = int(match.group(2))
    if not 1 <= port <= 65535:
        raise ProxyRequestRejected("Invalid CONNECT port")

    return ConnectTarget(host=host, port=port)
