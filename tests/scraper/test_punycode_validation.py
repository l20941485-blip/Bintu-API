import pytest

from bintu_api.scraper.fetcher import TargetURLRejected, _parse_target
from bintu_api.settings import Settings

SETTINGS = Settings(api_key="", rapidapi_proxy_secret="")


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/",
        "https://xn--mnchen-3ya.de/",
        "https://xn--e1afmkfd.xn--p1ai/",
        "https://münchen.de/",
        "https://XN--MNCHEN-3YA.DE/",
        "https://🐴.example/",
        "https://✪df.ws/",
    ],
)
def test_valid_punycode_urls_parse(url):
    parsed, host, port, path = _parse_target(url, SETTINGS)

    assert parsed.scheme in {"http", "https"}
    assert host
    assert port in {80, 443}
    assert path.startswith("/")


@pytest.mark.parametrize(
    "url",
    [
        "https://xn--/",
        "https://xn--a/",
        "https://xn--.example.com/",
    ],
)
def test_invalid_punycode_urls_are_rejected(url):
    with pytest.raises(TargetURLRejected):
        _parse_target(url, SETTINGS)


@pytest.fixture
def client(bypass_robots_enforcement):
    from fastapi.testclient import TestClient

    from main import create_app

    settings = Settings(
        api_key="",
        rapidapi_proxy_secret="",
        require_auth=False,
        render_js_enabled=False,
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def test_invalid_punycode_maps_to_invalid_or_unsafe_url(client):
    response = client.get(
        "/api/v1/scrape/text",
        params={"url": "https://xn--/"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_or_unsafe_url"

def test_normalize_idn_host_boundaries_and_rejections():
    import idna

    from bintu_api.scraper.host_norm import normalize_idn_host

    assert normalize_idn_host("  Example.COM.  ") == "example.com"
    assert normalize_idn_host("🐴.example") == "xn--8o8h.example"

    max_label = "a" * 63
    assert normalize_idn_host(f"{max_label}.example.com") == f"{max_label}.example.com"

    with pytest.raises(idna.IDNAError):
        normalize_idn_host(f"{'a' * 64}.example.com")

    with pytest.raises(idna.IDNAError):
        normalize_idn_host("-bad.example.com")

    with pytest.raises(idna.IDNAError):
        normalize_idn_host("bad-.example.com")

    with pytest.raises(idna.IDNAError):
        normalize_idn_host("xn--invalid-ace.example.com")
