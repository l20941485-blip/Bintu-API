"""Guard the MCP initialize instruction contract."""

from bintu_api.mcp.protocol import SERVER_INSTRUCTIONS


def test_initialize_instructions_contain_required_contract() -> None:
    required = (
        "200,000-character ceiling by default",
        "selected mode and max_tokens budget",
        "Token counts are approximate.",
        "no subscriptions, no SSE streams; POST",
    )

    for phrase in required:
        assert phrase in SERVER_INSTRUCTIONS


def test_initialize_instructions_end_with_authentication_contract() -> None:
    assert SERVER_INSTRUCTIONS.endswith(
        "tools/call requires X-API-Key or Authorization: Bearer."
    )


def test_initialize_instructions_are_ascii() -> None:
    assert SERVER_INSTRUCTIONS.isascii()
