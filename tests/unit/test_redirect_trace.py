from bintu_api.common.fetch import FetchedHTML, RedirectHop


def test_redirect_hop_records_url_and_status():
    hop = RedirectHop(
        url="https://example.com/intermediate",
        status=301,
    )

    assert hop.url == "https://example.com/intermediate"
    assert hop.status == 301


def test_fetched_html_defaults_to_no_redirect_hops():
    document = FetchedHTML(
        body=b"<html></html>",
        charset="utf-8",
    )

    assert document.redirects == ()
    assert document.redirect_count is None


def test_fetched_html_preserves_redirect_hops():
    hops = (
        RedirectHop(
            url="https://example.com/intermediate",
            status=301,
        ),
        RedirectHop(
            url="https://example.com/final",
            status=302,
        ),
    )
    document = FetchedHTML(
        body=b"<html></html>",
        charset="utf-8",
        final_url="https://example.com/final",
        status=200,
        redirect_count=2,
        redirects=hops,
    )

    assert document.redirects == hops
    assert document.redirect_count == 2
