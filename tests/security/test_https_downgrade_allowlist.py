from unittest.mock import patch

from bintu_api.scraper.fetcher import fetch_html_document
from bintu_api.settings import Settings


class _StubSettings(Settings):
    def __init__(self, allowed_domains):
        super().__init__(
            api_key="test",
            rapidapi_proxy_secret="",
            request_timeout_seconds=0.01,
            max_redirects=1,
            https_to_http_redirect_allowed_domains=allowed_domains,
        )


def _fake_fetch(url):
    class FakeResponse:
        def __init__(self, status, location=None):
            self.status = status
            self.reason = "Redirect" if status in (301, 302, 307, 308) else "OK"
            self._location = location
            self._body = b"<html><body>ok</body></html>"
            self._read = False

        def getheader(self, name, default=""):
            name = name.lower()
            if name == "location":
                return self._location or default
            if name == "content-type":
                return "text/html"
            return default

        def read(self, size=-1):
            if self._read:
                return b""
            self._read = True
            return self._body

    class FakeConnection:
        def __init__(self, response):
            self._response = response

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return self._response

        def close(self):
            pass

    def fake_make_connection(parsed, host, address, port, timeout):
        if parsed.scheme == "https":
            if parsed.path == "/redirect-to-evil":
                location = "http://evil-example.com/"
            else:
                location = f"http://{host}/"
            return FakeConnection(FakeResponse(302, location))
        return FakeConnection(FakeResponse(200))

    with patch(
        "bintu_api.scraper.fetcher._make_connection",
        side_effect=fake_make_connection,
    ), patch(
        "bintu_api.scraper.fetcher.resolve_public_addresses",
        return_value=("203.0.113.10",),
    ):
        return fetch_html_document(url, _StubSettings(("example.com",)))


def test_allowed_exact_domain_permits_downgrade():
    result = _fake_fetch("https://example.com/redirect-to-http")
    assert result.final_url == "http://example.com/"


def test_allowed_subdomain_permits_downgrade():
    result = _fake_fetch("https://www.example.com/redirect-to-http")
    assert result.final_url == "http://www.example.com/"


def test_unrelated_redirect_domain_rejects_downgrade():
    try:
        _fake_fetch("https://example.com/redirect-to-evil")
    except Exception as error:
        assert type(error).__name__ == "TargetURLRejected"
    else:
        raise AssertionError("Expected HTTPS-to-HTTP downgrade to be rejected")
