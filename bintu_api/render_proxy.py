"""Connection primitives for a future guarded rendering proxy.

Not a complete proxy. Not integrated with Chromium. S9 remains open.
"""

from __future__ import annotations

import ipaddress
import math
import socket

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
