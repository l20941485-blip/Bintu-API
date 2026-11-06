"""Direct HTTPS pinning tests; sockets and TLS wrapping are mocked."""

from unittest.mock import MagicMock, patch

import pytest

from bintu_api.scraper import _PinnedHTTPSConnection


@pytest.mark.parametrize(
    "address",
    ["93.184.216.34", "2001:4860:4860::8888"],
)
def test_https_connects_to_validated_ip_and_preserves_tls_hostname(address):
    raw_socket = MagicMock()
    tls_socket = MagicMock()
    context = MagicMock()
    context.wrap_socket.return_value = tls_socket

    with patch(
        "bintu_api.scraper.ssl.create_default_context",
        return_value=context,
    ) as default_context:
        connection = _PinnedHTTPSConnection(
            "target.example",
            address,
            443,
            3.0,
        )

    try:
        with patch(
            "bintu_api.scraper.socket.create_connection",
            return_value=raw_socket,
        ) as connect:
            connection.connect()

        default_context.assert_called_once_with()
        connect.assert_called_once_with((address, 443), 3.0, None)
        context.wrap_socket.assert_called_once_with(
            raw_socket,
            server_hostname="target.example",
        )
        assert connection.sock is tls_socket
    finally:
        connection.close()
