"""Test Error Boundary for Bintu.

This module owns a focused responsibility within the service and must remain isolated from unrelated transport or persistence concerns.

Important boundaries, invariants, and compatibility notes are documented here so the module stays focused on its owned behavior without drifting into unrelated routing or storage concerns.
"""

from bintu_api.errors.codes import ERROR_CODES, normalize_error_code
from bintu_api.errors.tool_errors import ToolError, build_mcp_tool_error_result
from bintu_api.errors.tool_errors import ToolError as LegacyToolError


def test_legacy_tool_error_import_is_backward_compatible():
    assert LegacyToolError is ToolError


def test_tool_error_result_preserves_existing_optional_field_behavior():
    result = build_mcp_tool_error_result(ToolError("example_error", "A message."))

    assert result == {
        "content": [{"type": "text", "text": "example_error: A message"}],
        "structuredContent": {
            "error": {
                "code": "example_error",
                "message": "A message.",
                "retryable": False,
            }
        },
        "isError": True,
    }


def test_tool_error_result_includes_hint_retryable_and_retry_with():
    result = build_mcp_tool_error_result(
        ToolError(
            "upstream_rate_limited",
            "The target is rate limiting requests.",
            hint="Wait before retrying.",
            retryable=True,
            retry_with="retry_after_delay",
        )
    )

    error = result["structuredContent"]["error"]
    assert error["hint"] == "Wait before retrying."
    assert error["retryable"] is True
    assert error["retry_with"] == "retry_after_delay"
    text = result["content"][0]["text"]
    assert ". Hint: Wait before retrying." in text
    assert text.endswith(". Retry with: retry_after_delay")


def test_error_code_catalog_contains_existing_application_codes():
    assert {
        "invalid_or_unsafe_url",
        "upstream_rate_limited",
        "blocked_by_robots",
        "premium_required",
        "reader_snapshot_unavailable",
    } <= ERROR_CODES
    assert all(code == code.lower() and code.replace("_", "").isalnum() for code in ERROR_CODES)


def test_error_code_normalization_preserves_stable_snake_case_contract():
    assert normalize_error_code("UpstreamRateLimited") == "upstream_rate_limited"
    assert normalize_error_code("upstream-rate-limited") == "upstream_rate_limited"
    assert normalize_error_code("invalidOrUnsafeUrl") == "invalid_or_unsafe_url"
    assert normalize_error_code("  RENDER-JS Disabled  ") == "render_js_disabled"
    assert ToolError("UpstreamRateLimited", "message").code == "upstream_rate_limited"

def test_http_mcp_error_response_normalizes_code_and_includes_structured_content():
    from bintu_api.mcp.http_api import _mcp_error_response

    result = _mcp_error_response(
        "Render-JS Disabled",
        "JavaScript rendering is disabled on this service.",
        "  Retry with render_js=false.  ",
    )

    assert result["isError"] is True
    assert result["structuredContent"] == {
        "error": {
            "code": "render_js_disabled",
            "message": "JavaScript rendering is disabled on this service.",
            "hint": "Retry with render_js=false.",
            "retryable": False,
        }
    }
    assert result["content"][0]["text"].startswith("render_js_disabled:")
    assert ". Hint: Retry with render_js=false." in result["content"][0]["text"]
