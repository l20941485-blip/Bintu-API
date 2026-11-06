"""Test Error Boundary for Bintu.

This module owns a focused responsibility within the service and must remain isolated from unrelated transport or persistence concerns.

Important boundaries, invariants, and compatibility notes are documented here so the module stays focused on its owned behavior without drifting into unrelated routing or storage concerns.
"""

from bintu_api.errors.codes import ERROR_CODES, normalize_error_code
from bintu_api.errors.tool_errors import ToolError, build_mcp_tool_error_result
from bintu_api.tool_errors import ToolError as LegacyToolError


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
    assert result["content"][0]["text"].endswith(". Hint: Wait before retrying.")


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
