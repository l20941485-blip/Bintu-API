from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from bintu_api.rag.ingestion_workflow import ingest_url_to_knowledge_core
from bintu_api.rag.refresh_workflow import refresh_user_knowledge


def _make_settings():
    return SimpleNamespace(
        rapidapi_proxy_secret=None,
        trust_proxy_headers=False,
    )


def _make_request(with_supabase: bool = True):
    limiter = SimpleNamespace(check=lambda _identity: None)
    client = object() if with_supabase else None
    return SimpleNamespace(
        headers={},
        client=SimpleNamespace(host="127.0.0.1"),
        app=SimpleNamespace(state=SimpleNamespace(supabase_client=client, rate_limiter=limiter)),
    )


def test_ingest_url_rejects_blank_url_and_whitespace_markdown() -> None:
    req = _make_request(with_supabase=True)
    settings = _make_settings()

    with pytest.raises(HTTPException) as blank_url_exc:
        asyncio.run(
            ingest_url_to_knowledge_core(
                req,
                settings,
                "   ",
                owner_identity="user_1",
            )
        )
    assert blank_url_exc.value.status_code == 422
    assert blank_url_exc.value.detail["code"] == "invalid_url"

    async def _fake_extract(*_args, **_kwargs):
        doc = SimpleNamespace(final_url="https://example.com/empty")
        res = SimpleNamespace(
            markdown="   \n\t  ",
            page_title="Empty",
            content_hash="abc",
            content_fingerprint="fp",
            extracted_at="2026-11-27T00:00:00Z",
        )
        return doc, res, "none", False

    with pytest.raises(HTTPException) as empty_md_exc:
        asyncio.run(
            ingest_url_to_knowledge_core(
                req,
                settings,
                "https://example.com/empty",
                owner_identity="user_1",
                extract_fn=_fake_extract,
            )
        )
    assert empty_md_exc.value.status_code == 422
    assert empty_md_exc.value.detail["code"] == "no_ingestable_content"


def test_ingest_url_rejects_invalid_token_budgets() -> None:
    req = _make_request(with_supabase=True)
    settings = _make_settings()

    with pytest.raises(ValueError, match="max_tokens"):
        asyncio.run(
            ingest_url_to_knowledge_core(
                req,
                settings,
                "https://example.com",
                owner_identity="user_1",
                max_tokens=0,
            )
        )

    with pytest.raises(ValueError, match="overlap_tokens"):
        asyncio.run(
            ingest_url_to_knowledge_core(
                req,
                settings,
                "https://example.com",
                owner_identity="user_1",
                max_tokens=1000,
                overlap_tokens=1000,
            )
        )


def test_refresh_user_knowledge_rejects_missing_canonical_url(monkeypatch) -> None:
    from bintu_api.rag import refresh_workflow as refresh_mod

    class _FakeDetailRepo:
        def __init__(self, _client):
            pass

        async def get_document_details(self, **_kwargs):
            return {"document": {"canonical_url": "   "}}

    monkeypatch.setattr(refresh_mod, "SupabaseDocumentDetailRepository", _FakeDetailRepo)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            refresh_user_knowledge(
                _make_request(with_supabase=True),
                _make_settings(),
                "user_1",
                "doc_1",
            )
        )
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "invalid_document_source"
