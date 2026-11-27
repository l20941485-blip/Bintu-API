from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from bintu_api.extraction.cache_store import (
    REQUIRED_SCRAPE_CACHE_COLUMNS,
    verify_scrape_cache_schema,
)
from bintu_api.extraction.dedupe import dedupe_paragraphs
from bintu_api.settings import Settings
from main import create_app


class _FakeQuery:
    def __init__(self, should_fail: bool = False, error_msg: str = "") -> None:
        self._should_fail = should_fail
        self._error_msg = error_msg

    def select(self, _columns: str) -> _FakeQuery:
        return self

    def limit(self, _count: int) -> _FakeQuery:
        return self

    async def execute(self) -> dict[str, object]:
        if self._should_fail:
            raise RuntimeError(self._error_msg)
        return {"data": []}


class _FakeClient:
    def __init__(self, should_fail: bool = False, error_msg: str = "") -> None:
        self._should_fail = should_fail
        self._error_msg = error_msg

    def table(self, _name: str) -> _FakeQuery:
        return _FakeQuery(should_fail=self._should_fail, error_msg=self._error_msg)


@pytest.mark.asyncio
async def test_verify_scrape_cache_schema_ok() -> None:
    result = await verify_scrape_cache_schema(_FakeClient(should_fail=False))
    assert result["ok"] is True
    assert result["checked_columns"] == len(REQUIRED_SCRAPE_CACHE_COLUMNS)
    assert result["missing_columns"] == []
    assert result["error"] is None


@pytest.mark.asyncio
async def test_verify_scrape_cache_schema_missing_column() -> None:
    result = await verify_scrape_cache_schema(
        _FakeClient(
            should_fail=True,
            error_msg="column scrape_cache.content_fingerprint does not exist",
        )
    )
    assert result["ok"] is False
    assert "content_fingerprint" in result["missing_columns"]


def test_dedupe_paragraphs_skips_fences_and_headings() -> None:
    sample = (
        "# Heading One\n\n"
        "This is a sufficiently long repeated paragraph for testing deduplication.\n\n"
        "```python\n"
        "This is a sufficiently long repeated paragraph for testing deduplication.\n"
        "```\n\n"
        "This is a sufficiently long repeated paragraph for testing deduplication."
    )
    cleaned, removed = dedupe_paragraphs(sample, min_chars=40)
    assert removed == 1
    assert cleaned.count("This is a sufficiently long repeated paragraph for testing deduplication.") == 2


def test_healthz_deep_reflects_schema_state(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _no_client(_settings: Settings):
        return None

    monkeypatch.setattr("main.create_supabase_client", _no_client)
    app = create_app(Settings(api_key="test-api-key", rapidapi_proxy_secret="test-proxy-secret"))
    with TestClient(app) as client:
        res = client.get("/healthz/deep")
        assert res.status_code == 503
        assert res.json()["status"] == "degraded"
