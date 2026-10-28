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


MAX_CONNECT_HEAD_BYTES = 16384
MAX_CONNECT_LINE_BYTES = 4096
MAX_CONNECT_HEADERS = 64


@dataclass(frozen=True)
class ConnectRequestHead:
    target: ConnectTarget
    headers: tuple[tuple[str, str], ...]


def parse_connect_request_head(data: bytes) -> ConnectRequestHead:
    """Parse exactly one CONNECT head, including its final CRLFCRLF.

    No body, tunnel bytes, or subsequent request may be included.
    A future stream reader must separate and bound input before calling.
    This function performs no network access or destination authorization.
    """
    if not data or len(data) > MAX_CONNECT_HEAD_BYTES:
        raise ProxyRequestRejected("Invalid request-head size")

    if not data.endswith(b"\r\n\r\n"):
        raise ProxyRequestRejected("Incomplete request head")

    lines = data[:-4].split(b"\r\n")
    if any(len(line) > MAX_CONNECT_LINE_BYTES for line in lines):
        raise ProxyRequestRejected("Request line or header too long")

    if any(
        byte < 32 or byte > 126
        for line in lines
        for byte in line
    ):
        raise ProxyRequestRejected("Unsupported request-head characters")

    request_line = lines[0].decode("ascii")
    match = re.fullmatch(r"CONNECT ([^ ]+) HTTP/1\.1", request_line)
    if match is None:
        raise ProxyRequestRejected("Only CONNECT HTTP/1.1 is supported")

    target = parse_connect_authority(match.group(1))

    if len(lines) - 1 > MAX_CONNECT_HEADERS:
        raise ProxyRequestRejected("Too many headers")

    headers: list[tuple[str, str]] = []
    seen: set[str] = set()
    host_target = None

    for raw_line in lines[1:]:
        line = raw_line.decode("ascii")
        name, separator, value = line.partition(":")
        if not separator or re.fullmatch(
            r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+",
            name,
        ) is None:
            raise ProxyRequestRejected("Invalid header field")

        name = name.lower()
        value = value.strip(" ")

        if name in seen:
            raise ProxyRequestRejected("Duplicate header field")
        seen.add(name)

        if name in {"content-length", "transfer-encoding", "expect", "upgrade"}:
            raise ProxyRequestRejected("Unsupported CONNECT framing")

        if name == "host":
            host_target = parse_connect_authority(value)

        headers.append((name, value))

    if host_target is None or host_target != target:
        raise ProxyRequestRejected("Host must match CONNECT target")

    return ConnectRequestHead(target=target, headers=tuple(headers))
