import pytest

from bintu_api.mcp.assistant import (
    ASSISTANT_TOOL_NAME,
    AssistantArguments,
    assistant_tool_definition,
)


def test_assistant_tool_name_is_unique() -> None:
    assert ASSISTANT_TOOL_NAME == "bintu_assistant"


def test_assistant_tool_definition_exposes_expected_metadata() -> None:
    definition = assistant_tool_definition()

    assert definition["name"] == ASSISTANT_TOOL_NAME
    assert definition["title"] == "Bintu Assistant"
    assert definition["inputSchema"]["required"] == ["domain", "action"]


def test_assistant_requires_domain_and_action() -> None:
    with pytest.raises(ValueError):
        AssistantArguments.model_validate({})


def test_extraction_scrape_requires_url() -> None:
    with pytest.raises(ValueError):
        AssistantArguments.model_validate(
            {
                "domain": "extraction",
                "action": "scrape",
            }
        )


def test_extraction_scrape_accepts_url() -> None:
    arguments = AssistantArguments.model_validate(
        {
            "domain": "extraction",
            "action": "scrape",
            "url": "https://example.com/article",
        }
    )

    assert arguments.url == "https://example.com/article"
    assert arguments.max_tokens == 6000


def test_knowledge_ask_requires_query_and_document() -> None:
    with pytest.raises(ValueError):
        AssistantArguments.model_validate(
            {
                "domain": "knowledge",
                "action": "ask_knowledge",
                "query": "What does this say?",
            }
        )

    with pytest.raises(ValueError):
        AssistantArguments.model_validate(
            {
                "domain": "knowledge",
                "action": "ask_knowledge",
                "document_id": "doc_123",
            }
        )


def test_knowledge_ask_accepts_query_and_document() -> None:
    arguments = AssistantArguments.model_validate(
        {
            "domain": "knowledge",
            "action": "ask_knowledge",
            "query": "What does this document say?",
            "document_id": "doc_123",
        }
    )

    assert arguments.query == "What does this document say?"
    assert arguments.document_id == "doc_123"
    assert arguments.limit == 5


def test_extraction_rejects_knowledge_action() -> None:
    with pytest.raises(ValueError):
        AssistantArguments.model_validate(
            {
                "domain": "extraction",
                "action": "ask_knowledge",
                "url": "https://example.com/article",
            }
        )


def test_knowledge_rejects_scrape_action() -> None:
    with pytest.raises(ValueError):
        AssistantArguments.model_validate(
            {
                "domain": "knowledge",
                "action": "scrape",
                "query": "What does this document say?",
                "document_id": "doc_123",
            }
        )


def test_knowledge_core_unavailable_includes_recovery_hint() -> None:
    import asyncio
    from types import SimpleNamespace

    from bintu_api.mcp.assistant import call_assistant_tool

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(supabase_client=None))
    )
    settings = SimpleNamespace()
    result = asyncio.run(
        call_assistant_tool(
            request,
            settings,
            "req_test",
            {
                "arguments": {
                    "domain": "knowledge",
                    "action": "ask_knowledge",
                    "query": "What does this document say?",
                    "document_id": "doc_123",
                }
            },
        )
    )

    assert result["isError"] is True
    error_text = result["content"][0]["text"]
    assert "knowledge_core_unavailable: The knowledge core is not configured." in error_text
    assert "domain=extraction" in error_text
