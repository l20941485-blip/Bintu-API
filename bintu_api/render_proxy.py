"""Connection primitives for a future guarded rendering proxy.

Not a complete proxy. Not integrated with Chromium. S9 remains open.
"""

from __future__ import annotations

import ipaddress
import math
import socket
import time

from bintu_api.render_proxy_protocol import (
    MAX_CONNECT_HEAD_BYTES,
    ConnectRequestHead,
    ProxyRequestRejected,
    parse_connect_request_head,
)
from bintu_api.settings import Settings


def open_validated_socket(url: str, settings: Settings) -> socket.socket:
    """Open TCP to a validated numeric destination.

    The caller owns the returned socket and must close it.
    The timeout applies per connection attempt, not to DNS resolution
    or the complete operation. This function is blocking.
    """
    from bintu_api.scraper import _parse_target, resolve_public_addresses

    timeout = float(settings.request_timeout_seconds)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Connection timeout must be finite and positive")

    _, host, port, _ = _parse_target(url, settings)
    addresses = resolve_public_addresses(host, port)
    last_error: OSError | None = None

    for address in addresses:
        numeric = ipaddress.ip_address(address)
        family = socket.AF_INET6 if numeric.version == 6 else socket.AF_INET
        endpoint = (
            (str(numeric), port, 0, 0)
            if numeric.version == 6
            else (str(numeric), port)
        )
        candidate = socket.socket(family, socket.SOCK_STREAM)

        try:
            candidate.settimeout(timeout)
            candidate.connect(endpoint)
        except OSError as error:
            candidate.close()
            last_error = error
            continue
        except BaseException:
            candidate.close()
            raise

        return candidate

    if last_error is not None:
        raise last_error
    raise OSError("No validated destination could be connected to")


def read_connect_request_head(
    client: socket.socket,
    *,
    timeout_seconds: float = 5.0,
) -> tuple[ConnectRequestHead, bytes]:
    """Read and parse one bounded CONNECT head from a connected socket.

    Return the parsed head and any bytes read beyond its terminator.
    Apply one overall read deadline and restore the original socket timeout.
    The caller retains ownership of the socket, including after errors.

    No DNS resolution, destination authorization, forwarding, or response.
    """
    timeout = float(timeout_seconds)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Request-head timeout must be finite and positive")

    original_timeout = client.gettimeout()
    deadline = time.monotonic() + timeout
    buffer = bytearray()

    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProxyRequestRejected("Request-head deadline exceeded")

            capacity = MAX_CONNECT_HEAD_BYTES - len(buffer)
            if capacity <= 0:
                raise ProxyRequestRejected("Request head too large")

            client.settimeout(remaining)
            try:
                chunk = client.recv(min(4096, capacity))
            except TimeoutError as error:
                raise ProxyRequestRejected(
                    "Request-head deadline exceeded"
                ) from error

            if time.monotonic() >= deadline:
                raise ProxyRequestRejected("Request-head deadline exceeded")

            if not chunk:
                raise ProxyRequestRejected("EOF before complete request head")

            buffer.extend(chunk)
            marker = buffer.find(b"\r\n\r\n")
            if marker != -1:
                end = marker + 4
                head = parse_connect_request_head(bytes(buffer[:end]))
                return head, bytes(buffer[end:])
    finally:
        client.settimeout(original_timeout)
