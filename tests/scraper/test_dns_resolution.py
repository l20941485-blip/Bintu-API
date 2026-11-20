import socket

import pytest

from bintu_api.scraper.fetcher import resolve_public_addresses


def test_empty_dns_result_is_upstream_connection_error(monkeypatch):
    """An empty resolver result is an upstream DNS condition, not an unsafe URL."""

    def fake_getaddrinfo(*args, **kwargs):
        return []

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(OSError):
        resolve_public_addresses("empty-result.example", 443)


def test_dns_gaierror_is_upstream_connection_error(monkeypatch):
    """A resolver outage must not be classified as an unsafe URL."""

    def fake_getaddrinfo(*args, **kwargs):
        raise socket.gaierror("name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(OSError):
        resolve_public_addresses("resolver-outage.example", 443)
