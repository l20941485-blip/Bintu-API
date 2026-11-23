from bintu_api.common.fetch import RedirectHop
from bintu_api.scraper.fetcher import _rendered_redirect_hops


class FakeRequest:
    def __init__(self, url, redirected_from=None):
        self.url = url
        self.redirected_from = redirected_from


def test_rendered_redirect_hops_are_empty_without_redirects():
    request = FakeRequest("https://example.com/final")

    assert _rendered_redirect_hops(request) == ()


def test_rendered_redirect_hops_record_prior_urls():
    first = FakeRequest("https://example.com/first")
    second = FakeRequest(
        "https://example.com/second",
        redirected_from=first,
    )
    final = FakeRequest(
        "https://example.com/final",
        redirected_from=second,
    )

    hops = _rendered_redirect_hops(final)

    assert hops == (
        RedirectHop(url="https://example.com/first"),
        RedirectHop(url="https://example.com/second"),
    )
