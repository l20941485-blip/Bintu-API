from unittest.mock import patch

from bintu_api.scraper.robots import _fetch_robots_text


class _StubSettings:
    request_timeout_seconds = 8.0
    max_redirects = 5
    user_agent = "BintuBot"


def test_robots_fetch_falls_back_to_next_address():
    """A failed first address must not prevent a working second address."""

    addresses = ("2001:db8::1", "203.0.113.10")
    attempts = []
    timeouts = []

    class FakeConnection:
        def __init__(self, address):
            self.address = address
            self.closed = False

        def request(self, *args, **kwargs):
            attempts.append(self.address)
            if self.address == "2001:db8::1":
                raise OSError("IPv6 route unavailable")

        def getresponse(self):
            class FakeResponse:
                status = 404

            return FakeResponse()

        def close(self):
            self.closed = True

    def fake_make_connection(parsed, host, address, port, timeout):
        timeouts.append(timeout)
        return FakeConnection(address)

    with patch(
        "bintu_api.scraper.robots.resolve_public_addresses",
        return_value=addresses,
    ), patch(
        "bintu_api.scraper.robots._make_connection",
        side_effect=fake_make_connection,
    ):
        result = _fetch_robots_text("https://example.com", _StubSettings())

    assert attempts == list(addresses)
    assert len(timeouts) == len(addresses)
    assert all(timeout > 0 for timeout in timeouts)
    assert timeouts[0] == timeouts[1]
    assert result is None
