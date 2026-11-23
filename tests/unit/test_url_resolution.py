from bintu_api.common.resolution import classify_content_type


def test_html_content_type_is_classified():
    assert classify_content_type("text/html; charset=utf-8") == "html"


def test_xhtml_content_type_is_classified_as_html():
    assert classify_content_type("application/xhtml+xml") == "html"


def test_pdf_content_type_is_classified():
    assert classify_content_type("application/pdf") == "pdf"


def test_json_content_type_is_classified():
    assert classify_content_type("application/json") == "json"


def test_text_json_content_type_is_classified():
    assert classify_content_type("text/json") == "json"


def test_plain_text_content_type_is_classified():
    assert classify_content_type("text/plain; charset=utf-8") == "text"


def test_image_content_type_is_classified():
    assert classify_content_type("image/png") == "image"


def test_missing_content_type_is_unsupported():
    assert classify_content_type(None) == "unsupported"


def test_empty_content_type_is_unsupported():
    assert classify_content_type("") == "unsupported"


def test_unknown_content_type_is_unsupported():
    assert classify_content_type("application/octet-stream") == "unsupported"


def test_normalize_url_lowercases_scheme_and_host():
    from bintu_api.common.resolution import normalize_url

    assert normalize_url("HTTPS://EXAMPLE.COM/Path") == "https://example.com/Path"


def test_normalize_url_removes_fragment():
    from bintu_api.common.resolution import normalize_url

    assert normalize_url("https://example.com/page#section") == "https://example.com/page"


def test_normalize_url_removes_default_https_port():
    from bintu_api.common.resolution import normalize_url

    assert normalize_url("https://example.com:443/page") == "https://example.com/page"


def test_normalize_url_removes_default_http_port():
    from bintu_api.common.resolution import normalize_url

    assert normalize_url("http://example.com:80/page") == "http://example.com/page"


def test_normalize_url_preserves_nondefault_port():
    from bintu_api.common.resolution import normalize_url

    assert normalize_url("http://example.com:8080/page") == "http://example.com:8080/page"


def test_normalize_url_preserves_query():
    from bintu_api.common.resolution import normalize_url

    assert (
        normalize_url("https://example.com/search?q=python")
        == "https://example.com/search?q=python"
    )


def test_normalize_url_adds_root_path():
    from bintu_api.common.resolution import normalize_url

    assert normalize_url("https://example.com") == "https://example.com/"


def test_normalize_url_rejects_non_http_scheme():
    import pytest
    from bintu_api.common.resolution import normalize_url

    with pytest.raises(ValueError):
        normalize_url("ftp://example.com/file")


def test_normalize_url_rejects_missing_host():
    import pytest
    from bintu_api.common.resolution import normalize_url

    with pytest.raises(ValueError):
        normalize_url("https://")


def test_validate_url_returns_normalized_url():
    from bintu_api.common.resolution import validate_url
    from bintu_api.settings import Settings

    settings = Settings(
        api_key="",
        rapidapi_proxy_secret="",
        render_js_enabled=False,
    )

    assert (
        validate_url("HTTPS://EXAMPLE.COM:443/page#section", settings)
        == "https://example.com/page"
    )


def test_validate_url_rejects_disallowed_port():
    import pytest
    from bintu_api.common.resolution import validate_url
    from bintu_api.scraper.fetcher import TargetURLRejected
    from bintu_api.settings import Settings

    settings = Settings(
        api_key="",
        rapidapi_proxy_secret="",
        render_js_enabled=False,
    )

    with pytest.raises(TargetURLRejected):
        validate_url("http://example.com:8080/", settings)


def test_validate_url_rejects_embedded_credentials():
    import pytest
    from bintu_api.common.resolution import validate_url
    from bintu_api.scraper.fetcher import TargetURLRejected
    from bintu_api.settings import Settings

    settings = Settings(
        api_key="",
        rapidapi_proxy_secret="",
        render_js_enabled=False,
    )

    with pytest.raises(TargetURLRejected):
        validate_url("https://user:password@example.com/", settings)


def test_html_uses_direct_fetch_by_default():
    from bintu_api.common.resolution import select_fetch_strategy

    assert (
        select_fetch_strategy("text/html; charset=utf-8")
        == "direct_html"
    )


def test_html_uses_rendered_fetch_when_requested():
    from bintu_api.common.resolution import select_fetch_strategy

    assert (
        select_fetch_strategy("text/html", render_js=True)
        == "rendered_html"
    )


def test_pdf_uses_specialized_strategy():
    from bintu_api.common.resolution import select_fetch_strategy

    assert select_fetch_strategy("application/pdf") == "specialized_pdf"


def test_json_uses_specialized_strategy():
    from bintu_api.common.resolution import select_fetch_strategy

    assert select_fetch_strategy("application/json") == "specialized_json"


def test_plain_text_uses_specialized_strategy():
    from bintu_api.common.resolution import select_fetch_strategy

    assert select_fetch_strategy("text/plain") == "specialized_text"


def test_image_is_unsupported():
    from bintu_api.common.resolution import select_fetch_strategy

    assert select_fetch_strategy("image/png") == "unsupported"


def test_missing_content_type_is_unsupported():
    from bintu_api.common.resolution import select_fetch_strategy

    assert select_fetch_strategy(None) == "unsupported"
