from bintu_api.errors.http_errors import translate_upstream_error
from bintu_api.scraper.fetcher import UpstreamHTTPError


def test_upstream_404_is_not_retryable():
    error = UpstreamHTTPError(404, "Not Found")
    response = translate_upstream_error(
        error,
        url="https://example.com/missing",
        request_id="test-request",
    )

    assert response.status_code == 502
    assert response.detail["code"] == "upstream_not_found"
    assert response.detail["upstream_status"] == 404
    assert "do not retry the same URL" in response.detail["hint"]
