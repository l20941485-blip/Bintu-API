from bintu_api.errors.http_errors import translate_upstream_error
from bintu_api.scraper.fetcher import (
    TargetURLRejected,
    TooManyRedirects,
    UnsupportedContentEncoding,
    UnsupportedMediaType,
    UpstreamRenderError,
)


def test_target_url_rejection_does_not_expose_raw_exception() -> None:
    error = TargetURLRejected("secret-token-and-internal-context")
    response = translate_upstream_error(
        error,
        url="https://example.com",
        request_id="test-request",
    )

    assert response.status_code == 400
    assert response.detail["code"] == "invalid_or_unsafe_url"
    assert "secret-token-and-internal-context" not in response.detail["message"]


def test_unsupported_media_type_does_not_expose_raw_exception() -> None:
    error = UnsupportedMediaType("secret-upstream-context")
    response = translate_upstream_error(
        error,
        url="https://example.com",
        request_id="test-request",
    )

    assert response.status_code == 415
    assert response.detail["code"] == "unsupported_media_type"
    assert "secret-upstream-context" not in response.detail["message"]


def test_unsupported_content_encoding_does_not_expose_raw_exception() -> None:
    error = UnsupportedContentEncoding("secret-upstream-context")
    response = translate_upstream_error(
        error,
        url="https://example.com",
        request_id="test-request",
    )

    assert response.status_code == 502
    assert response.detail["code"] == "unsupported_content_encoding"
    assert "secret-upstream-context" not in response.detail["message"]


def test_too_many_redirects_does_not_expose_raw_exception() -> None:
    error = TooManyRedirects("secret-upstream-context")
    response = translate_upstream_error(
        error,
        url="https://example.com",
        request_id="test-request",
    )

    assert response.status_code == 502
    assert response.detail["code"] == "too_many_redirects"
    assert "secret-upstream-context" not in response.detail["message"]


def test_render_error_does_not_expose_raw_exception() -> None:
    error = UpstreamRenderError("secret-upstream-context")
    response = translate_upstream_error(
        error,
        url="https://example.com",
        request_id="test-request",
    )

    assert response.status_code == 502
    assert response.detail["code"] == "upstream_render_error"
    assert "secret-upstream-context" not in response.detail["message"]
