from bintu_api.common.fetch import RedirectHop


def test_redirect_hop_contract_supports_multiple_hops():
    hops = (
        RedirectHop(url="https://example.com/first", status=301),
        RedirectHop(url="https://example.com/second", status=302),
    )

    assert len(hops) == 2
    assert hops[0].url == "https://example.com/first"
    assert hops[0].status == 301
    assert hops[1].url == "https://example.com/second"
    assert hops[1].status == 302
