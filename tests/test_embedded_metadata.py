"""Regression coverage for metadata IPv4 embedded in IPv6 addresses."""

import ipaddress
from unittest.mock import patch

import pytest

from bintu_api.scraper import (
    TargetURLRejected,
    _embedded_ipv4,
    _parse_target,
    resolve_public_addresses,
)
from bintu_api.settings import Settings

import socket


CASES = (
    "::ffff:169.254.169.254",
    "64:ff9b::a9fe:a9fe",
    "2002:a9fe:a9fe::",
)


@pytest.mark.parametrize("address", CASES)
def test_embedded_metadata_ipv4_is_extracted_correctly(address):
    assert _embedded_ipv4(
        ipaddress.IPv6Address(address)
    ) == ipaddress.IPv4Address("169.254.169.254")


@pytest.mark.parametrize("address", CASES)
def test_embedded_metadata_literal_is_rejected_without_dns(address):
    settings = Settings(api_key="", rapidapi_proxy_secret="")

    with patch("bintu_api.scraper.socket.getaddrinfo") as lookup:
        with pytest.raises(TargetURLRejected):
            _parse_target(f"http://[{address}]/", settings)

    lookup.assert_not_called()


@pytest.mark.parametrize("address", CASES)
def test_dns_answer_with_embedded_metadata_is_rejected(address):
    answer = (
        socket.AF_INET6,
        socket.SOCK_STREAM,
        socket.IPPROTO_TCP,
        "",
        (address, 80, 0, 0),
    )

    with patch(
        "bintu_api.scraper.socket.getaddrinfo",
        return_value=[answer],
    ):
        with pytest.raises(TargetURLRejected):
            resolve_public_addresses("metadata-wrapper.example", 80)


@pytest.mark.parametrize("address", CASES)
def test_public_answer_does_not_hide_embedded_metadata(address):
    answers = [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            ("8.8.8.8", 80),
        ),
        (
            socket.AF_INET6,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            (address, 80, 0, 0),
        ),
    ]

    with patch(
        "bintu_api.scraper.socket.getaddrinfo",
        return_value=answers,
    ):
        with pytest.raises(TargetURLRejected):
            resolve_public_addresses("metadata-wrapper.example", 80)
