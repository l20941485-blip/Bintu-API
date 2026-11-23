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



def _settings():
    from bintu_api.settings import Settings

    return Settings(
        api_key="",
        rapidapi_proxy_secret="",
        render_js_enabled=False,
    )


def test_resolve_target_normalizes_and_classifies_html():
    from bintu_api.common.resolution import resolve_target

    target = resolve_target(
        "HTTPS://EXAMPLE.COM/page#section",
        _settings(),
        content_type="text/html; charset=utf-8",
    )

    assert target.requested_url == "HTTPS://EXAMPLE.COM/page#section"
    assert target.normalized_url == "https://example.com/page"
    assert target.content_class == "html"
    assert target.fetch_strategy == "direct_html"
    assert target.final_url is None
    assert target.canonical_url is None
    assert target.redirect_count == 0


def test_resolve_target_selects_rendered_html():
    from bintu_api.common.resolution import resolve_target

    target = resolve_target(
        "https://example.com/",
        _settings(),
        content_type="text/html",
        render_js=True,
    )

    assert target.fetch_strategy == "rendered_html"


def test_resolve_target_classifies_pdf():
    from bintu_api.common.resolution import resolve_target

    target = resolve_target(
        "https://example.com/document.pdf",
        _settings(),
        content_type="application/pdf",
    )

    assert target.content_class == "pdf"
    assert target.fetch_strategy == "specialized_pdf"


def test_resolve_target_rejects_unsafe_url():
    import pytest

    from bintu_api.common.resolution import resolve_target
    from bintu_api.scraper.fetcher import TargetURLRejected

    with pytest.raises(TargetURLRejected):
        resolve_target(
            "http://example.com:8080/",
            _settings(),
        )


def test_resolve_target_defaults_to_unsupported():
    from bintu_api.common.resolution import resolve_target

    target = resolve_target(
        "https://example.com/",
        _settings(),
    )

    assert target.content_class == "unsupported"
    assert target.fetch_strategy == "unsupported"


def test_prepare_fetch_target_validates_before_fetch():
    from bintu_api.common.resolution import prepare_fetch_target

    target = prepare_fetch_target(
        "HTTPS://EXAMPLE.COM:443/page#section",
        _settings(),
        render_js=False,
    )

    assert target.normalized_url == "https://example.com/page"
    assert target.fetch_strategy == "unsupported"


def test_prepare_fetch_target_rejects_disallowed_port():
    import pytest

    from bintu_api.common.resolution import prepare_fetch_target
    from bintu_api.scraper.fetcher import TargetURLRejected

    with pytest.raises(TargetURLRejected):
        prepare_fetch_target(
            "http://example.com:8080/",
            _settings(),
        )


def test_refresh_resolved_target_uses_fetch_metadata():
    from bintu_api.common.fetch import FetchedHTML
    from bintu_api.common.resolution import prepare_fetch_target, refresh_resolved_target

    target = prepare_fetch_target(
        "https://example.com/start",
        _settings(),
    )
    document = FetchedHTML(
        body=b"<html><body>ok</body></html>",
        charset="utf-8",
        final_url="https://example.com/final",
        status=200,
        redirect_count=1,
        content_type="text/html; charset=utf-8",
        canonical_url="https://example.com/canonical",
    )

    refreshed = refresh_resolved_target(target, document)

    assert refreshed.requested_url == "https://example.com/start"
    assert refreshed.normalized_url == "https://example.com/start"
    assert refreshed.final_url == "https://example.com/final"
    assert refreshed.canonical_url == "https://example.com/canonical"
    assert refreshed.content_type == "text/html; charset=utf-8"
    assert refreshed.content_class == "html"
    assert refreshed.redirect_count == 1
    assert refreshed.fetch_strategy == "unsupported"


def test_refresh_resolved_target_tolerates_partial_document():
    from bintu_api.common.resolution import prepare_fetch_target, refresh_resolved_target

    target = prepare_fetch_target(
        "https://example.com/",
        _settings(),
    )

    class PartialDocument:
        final_url = "https://example.com/final"

    refreshed = refresh_resolved_target(target, PartialDocument())

    assert refreshed.final_url == "https://example.com/final"
    assert refreshed.canonical_url is None
    assert refreshed.content_type is None
    assert refreshed.content_class == "unsupported"
    assert refreshed.redirect_count == 0


def test_refresh_resolved_target_preserves_original_identity():
    from bintu_api.common.fetch import FetchedHTML
    from bintu_api.common.resolution import prepare_fetch_target, refresh_resolved_target

    target = prepare_fetch_target(
        "HTTPS://EXAMPLE.COM:443/page#section",
        _settings(),
    )
    document = FetchedHTML(
        body=b"<html></html>",
        charset="utf-8",
        final_url="https://example.com/redirected",
        status=200,
        redirect_count=1,
        content_type="text/html",
    )

    refreshed = refresh_resolved_target(target, document)

    assert refreshed.requested_url == "HTTPS://EXAMPLE.COM:443/page#section"
    assert refreshed.normalized_url == "https://example.com/page"
    assert refreshed.final_url == "https://example.com/redirected"
