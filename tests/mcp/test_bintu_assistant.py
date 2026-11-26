import json

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

def test_assistant_rejects_out_of_range_max_tokens() -> None:
    from pydantic import ValidationError

    for invalid_max in (99, 50001):
        with pytest.raises(ValidationError):
            AssistantArguments.model_validate(
                {
                    "domain": "extraction",
                    "action": "scrape",
                    "url": "https://example.com/article",
                    "max_tokens": invalid_max,
                }
            )


def test_assistant_rejects_out_of_range_limit() -> None:
    from pydantic import ValidationError

    for invalid_limit in (0, 21):
        with pytest.raises(ValidationError):
            AssistantArguments.model_validate(
                {
                    "domain": "knowledge",
                    "action": "ask_knowledge",
                    "query": "What does this document say?",
                    "document_id": "doc_123",
                    "limit": invalid_limit,
                }
            )


def test_assistant_forbids_extra_fields_and_validates_manage_knowledge() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AssistantArguments.model_validate(
            {
                "domain": "extraction",
                "action": "scrape",
                "url": "https://example.com/article",
                "unexpected_field": True,
            }
        )

    listed = AssistantArguments.model_validate(
        {
            "domain": "knowledge",
            "action": "manage_knowledge",
            "operation": "list",
        }
    )
    assert listed.operation == "list"

    with pytest.raises(ValueError, match="document_id"):
        AssistantArguments.model_validate(
            {
                "domain": "knowledge",
                "action": "manage_knowledge",
                "operation": "inspect",
            }
        )

    with pytest.raises(ValueError, match="confirm=true"):
        AssistantArguments.model_validate(
            {
                "domain": "knowledge",
                "action": "manage_knowledge",
                "operation": "delete",
                "document_id": "doc_123",
            }
        )

def test_knowledge_auth_error_surfaces_code_and_message(monkeypatch) -> None:
    import asyncio
    from types import SimpleNamespace

    from fastapi import HTTPException

    from bintu_api.mcp import assistant as assistant_module

    async def _fail_auth(_request, _settings):
        raise HTTPException(
            status_code=401,
            detail={"code": "session_expired", "message": "Sign in again."},
        )

    monkeypatch.setattr(assistant_module, "verify_supabase_user", _fail_auth)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(supabase_client=object()))
    )
    result = asyncio.run(
        assistant_module.call_assistant_tool(
            request,
            SimpleNamespace(),
            "req_auth",
            {
                "arguments": {
                    "domain": "knowledge",
                    "action": "manage_knowledge",
                    "operation": "list",
                }
            },
        )
    )

    assert result["isError"] is True
    assert "session_expired: Sign in again." in result["content"][0]["text"]


def test_manage_knowledge_list_delete_refresh_and_inspect(monkeypatch) -> None:
    import asyncio
    from types import SimpleNamespace

    from bintu_api.mcp import assistant as assistant_module

    async def _fake_user(_request, _settings):
        return "user_42"

    doc_record = SimpleNamespace(
        document_id="doc_1",
        title="Doc One",
        canonical_url="https://example.com/1",
        source_type="web",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-02T00:00:00Z",
        revision_count=1,
    )

    class _FakeDocRepo:
        def __init__(self, _client) -> None:
            pass

        async def list_documents(self, *, owner_identity: str, limit: int):
            assert owner_identity == "user_42"
            assert limit == 5
            return [doc_record], 1

    class _FakeDeleteRepo:
        def __init__(self, _client) -> None:
            pass

        async def delete_document(self, *, owner_identity: str, document_id: str) -> bool:
            assert owner_identity == "user_42"
            return document_id == "doc_1"

    async def _fake_refresh(*, request, settings, user_id: str, document_id: str):
        assert user_id == "user_42"
        assert document_id == "doc_1"
        return SimpleNamespace(
            document=SimpleNamespace(document_id="doc_1", title="Doc One"),
            revision_id="rev_2",
            revision=SimpleNamespace(source_url="https://example.com/1"),
            chunks=[{"index": 0}],
        )

    class _FakeDetailRepo:
        def __init__(self, _client) -> None:
            pass

        async def get_document_details(self, *, owner_identity: str, document_id: str):
            assert owner_identity == "user_42"
            if document_id != "doc_1":
                return None
            return {
                "document": {
                    "document_id": "doc_1",
                    "title": "Doc One",
                    "canonical_url": "https://example.com/1",
                    "source_type": "web",
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-02T00:00:00Z",
                },
                "revision": {
                    "revision_id": "rev_2",
                    "source_url": "https://example.com/1",
                    "final_url": "https://example.com/1",
                    "status": "ready",
                    "extracted_at": "2026-01-02T00:00:00Z",
                },
                "chunks": [{"index": 0}],
            }

    monkeypatch.setattr(assistant_module, "verify_supabase_user", _fake_user)
    monkeypatch.setattr(assistant_module, "SupabaseDocumentRepository", _FakeDocRepo)
    monkeypatch.setattr(assistant_module, "SupabaseDocumentDeletionRepository", _FakeDeleteRepo)
    monkeypatch.setattr(assistant_module, "refresh_user_knowledge", _fake_refresh)
    monkeypatch.setattr(assistant_module, "SupabaseDocumentDetailRepository", _FakeDetailRepo)

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(supabase_client=object()))
    )
    settings = SimpleNamespace()

    list_res = asyncio.run(
        assistant_module.call_assistant_tool(
            request,
            settings,
            "req_list",
            {"arguments": {"domain": "knowledge", "action": "manage_knowledge", "operation": "list"}},
        )
    )
    list_payload = json.loads(list_res["content"][0]["text"])
    assert list_payload["total"] == 1
    assert list_payload["documents"][0]["document_id"] == "doc_1"

    missing_del = asyncio.run(
        assistant_module.call_assistant_tool(
            request,
            settings,
            "req_del_missing",
            {
                "arguments": {
                    "domain": "knowledge",
                    "action": "manage_knowledge",
                    "operation": "delete",
                    "document_id": "missing_doc",
                    "confirm": True,
                }
            },
        )
    )
    assert missing_del["isError"] is True
    assert "document_not_found:" in missing_del["content"][0]["text"]

    del_res = asyncio.run(
        assistant_module.call_assistant_tool(
            request,
            settings,
            "req_del_ok",
            {
                "arguments": {
                    "domain": "knowledge",
                    "action": "manage_knowledge",
                    "operation": "delete",
                    "document_id": "doc_1",
                    "confirm": True,
                }
            },
        )
    )
    assert json.loads(del_res["content"][0]["text"])["deleted"] is True

    refresh_res = asyncio.run(
        assistant_module.call_assistant_tool(
            request,
            settings,
            "req_refresh",
            {
                "arguments": {
                    "domain": "knowledge",
                    "action": "manage_knowledge",
                    "operation": "refresh",
                    "document_id": "doc_1",
                }
            },
        )
    )
    refresh_payload = json.loads(refresh_res["content"][0]["text"])
    assert refresh_payload["revision_id"] == "rev_2"
    assert refresh_payload["chunk_count"] == 1

    inspect_res = asyncio.run(
        assistant_module.call_assistant_tool(
            request,
            settings,
            "req_inspect",
            {
                "arguments": {
                    "domain": "knowledge",
                    "action": "manage_knowledge",
                    "operation": "inspect",
                    "document_id": "doc_1",
                }
            },
        )
    )
    inspect_payload = json.loads(inspect_res["content"][0]["text"])
    assert inspect_payload["document"]["document_id"] == "doc_1"
    assert inspect_payload["chunk_count"] == 1


def test_add_knowledge_returns_ingested_summary(monkeypatch) -> None:
    import asyncio
    from types import SimpleNamespace

    from bintu_api.mcp import assistant as assistant_module

    async def _fake_user(_request, _settings):
        return "user_42"

    async def _fake_ingest(*, request, settings, user_id: str, url: str, max_tokens: int):
        assert user_id == "user_42"
        assert url == "https://example.com/guide"
        assert max_tokens == 6000
        return SimpleNamespace(
            document=SimpleNamespace(document_id="doc_9", title="Guide"),
            revision_id="rev_1",
            revision=SimpleNamespace(source_url="https://example.com/guide"),
            chunks=[{"index": 0}, {"index": 1}],
        )

    monkeypatch.setattr(assistant_module, "verify_supabase_user", _fake_user)
    monkeypatch.setattr(assistant_module, "ingest_public_knowledge", _fake_ingest)

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(supabase_client=object()))
    )
    res = asyncio.run(
        assistant_module.call_assistant_tool(
            request,
            SimpleNamespace(),
            "req_add",
            {
                "arguments": {
                    "domain": "knowledge",
                    "action": "add_knowledge",
                    "url": "https://example.com/guide",
                }
            },
        )
    )
    payload = json.loads(res["content"][0]["text"])
    assert payload["document_id"] == "doc_9"
    assert payload["revision_id"] == "rev_1"
    assert payload["chunk_count"] == 2
    assert payload["status"] == "ready"



def test_assistant_extraction_forwards_to_streamable_tools_call_result(monkeypatch) -> None:
    import asyncio
    from types import SimpleNamespace

    from bintu_api.mcp import assistant as assistant_module
    from bintu_api.mcp import streamable as streamable_module

    captured: dict = {}

    async def _fake_tools_call_result(*, request, settings, request_id, params):
        captured["request_id"] = request_id
        captured["params"] = params
        return {"content": [{"type": "text", "text": "forwarded"}]}

    monkeypatch.setattr(streamable_module, "_tools_call_result", _fake_tools_call_result)

    res = asyncio.run(
        assistant_module.call_assistant_tool(
            SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
            SimpleNamespace(),
            "req_ext",
            {
                "arguments": {
                    "domain": "extraction",
                    "action": "scrape",
                    "url": "https://example.com/article",
                    "max_tokens": 1200,
                }
            },
        )
    )

    assert res["content"][0]["text"] == "forwarded"
    assert captured["request_id"] == "req_ext"
    assert captured["params"]["name"] == streamable_module.TOOL_NAME
    assert captured["params"]["arguments"] == {
        "url": "https://example.com/article",
        "mode": "scrape",
        "max_tokens": 1200,
    }


def test_ask_knowledge_handles_missing_client_auth_error_and_answer(monkeypatch) -> None:
    import asyncio
    from types import SimpleNamespace

    from fastapi import HTTPException

    from bintu_api.mcp import assistant as assistant_module

    missing_client_res = asyncio.run(
        assistant_module.call_assistant_tool(
            SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(supabase_client=None))),
            SimpleNamespace(),
            "req_no_db",
            {
                "arguments": {
                    "domain": "knowledge",
                    "action": "ask_knowledge",
                    "document_id": "doc_1",
                    "query": "What is covered?",
                }
            },
        )
    )
    assert missing_client_res["isError"] is True
    assert "knowledge_core_unavailable:" in missing_client_res["content"][0]["text"]

    async def _unauthorized(_request, _settings):
        raise HTTPException(status_code=401, detail={"code": "invalid_session", "message": "Expired session"})

    monkeypatch.setattr(assistant_module, "verify_supabase_user", _unauthorized)
    req_with_db = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(supabase_client=object())))

    unauth_res = asyncio.run(
        assistant_module.call_assistant_tool(
            req_with_db,
            SimpleNamespace(),
            "req_unauth",
            {
                "arguments": {
                    "domain": "knowledge",
                    "action": "ask_knowledge",
                    "document_id": "doc_1",
                    "query": "What is covered?",
                }
            },
        )
    )
    assert unauth_res["isError"] is True
    assert "invalid_session: Expired session" in unauth_res["content"][0]["text"]

    async def _valid_user(_request, _settings):
        return "user_42"

    class _FakeRepo:
        def __init__(self, _client) -> None:
            pass

    class _FakeRetrieval:
        def __init__(self, _repo) -> None:
            pass

    class _FakeAnswerService:
        def __init__(self, _retrieval) -> None:
            pass

        async def answer(self, *, query: str, limit: int, owner_identity: str, document_id: str | None):
            assert query == "What is covered?"
            assert limit == 3
            assert owner_identity == "user_42"
            assert document_id == "doc_1"
            return SimpleNamespace(
                answer="Summary answer.",
                insufficient_evidence=False,
                citations=[
                    SimpleNamespace(
                        chunk_id="chk_0",
                        revision_id="rev_1",
                        document_id="doc_1",
                        source_url="https://example.com/doc",
                        final_url="https://example.com/doc",
                        heading_path=("Intro",),
                    )
                ],
            )

    monkeypatch.setattr(assistant_module, "verify_supabase_user", _valid_user)
    monkeypatch.setattr(assistant_module, "SupabaseRetrievalRepository", _FakeRepo)
    monkeypatch.setattr(assistant_module, "RagRetrievalService", _FakeRetrieval)
    monkeypatch.setattr(assistant_module, "RagAnswerService", _FakeAnswerService)

    ok_res = asyncio.run(
        assistant_module.call_assistant_tool(
            req_with_db,
            SimpleNamespace(),
            "req_ask_ok",
            {
                "arguments": {
                    "domain": "knowledge",
                    "action": "ask_knowledge",
                    "document_id": "doc_1",
                    "query": "What is covered?",
                    "limit": 3,
                }
            },
        )
    )
    assert not ok_res.get("isError")
    payload = json.loads(ok_res["content"][0]["text"])
    assert payload["domain"] == "knowledge"
    assert payload["action"] == "ask_knowledge"
    assert payload["answer"] == "Summary answer."
    assert payload["insufficient_evidence"] is False
    assert payload["citations"][0]["chunk_id"] == "chk_0"
    assert payload["citations"][0]["heading_path"] == ["Intro"]


def test_manage_knowledge_refresh_error_and_inspect_not_found(monkeypatch) -> None:
    import asyncio
    from types import SimpleNamespace

    from fastapi import HTTPException

    from bintu_api.mcp import assistant as assistant_module

    async def _valid_user(_request, _settings):
        return "user_42"

    async def _refresh_fails(*, request, settings, user_id, document_id):
        raise HTTPException(
            status_code=502,
            detail={"code": "refresh_failed", "message": "Upstream fetch failed"},
        )

    class _EmptyDetailRepo:
        def __init__(self, _client) -> None:
            pass

        async def get_document_details(self, *, owner_identity: str, document_id: str):
            return None

    monkeypatch.setattr(assistant_module, "verify_supabase_user", _valid_user)
    monkeypatch.setattr(assistant_module, "refresh_user_knowledge", _refresh_fails)
    monkeypatch.setattr(assistant_module, "SupabaseDocumentDetailRepository", _EmptyDetailRepo)

    req = SimpleNamespace(
        headers={},
        app=SimpleNamespace(state=SimpleNamespace(supabase_client=object())),
    )

    refresh_err = asyncio.run(
        assistant_module.call_assistant_tool(
            req,
            SimpleNamespace(),
            "req_refresh_err",
            {
                "arguments": {
                    "domain": "knowledge",
                    "action": "manage_knowledge",
                    "operation": "refresh",
                    "document_id": "doc_1",
                }
            },
        )
    )
    assert refresh_err["isError"] is True
    assert "refresh_failed: Upstream fetch failed" in refresh_err["content"][0]["text"]

    inspect_missing = asyncio.run(
        assistant_module.call_assistant_tool(
            req,
            SimpleNamespace(),
            "req_inspect_missing",
            {
                "arguments": {
                    "domain": "knowledge",
                    "action": "manage_knowledge",
                    "operation": "inspect",
                    "document_id": "doc_missing",
                }
            },
        )
    )
    assert inspect_missing["isError"] is True
    payload_text = inspect_missing["content"][0]["text"]
    assert "document_not_found:" in payload_text
    if payload_text.startswith("{"):
        assert json.loads(payload_text)["error"]["code"] == "document_not_found"
