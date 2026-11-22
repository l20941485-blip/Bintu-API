import pytest

from bintu_api.extraction.cache_store import (
    CachedMarkdown,
    get_cached_markdown,
    upsert_cached_markdown,
)

MARKDOWN = """# Example

First useful sentence.

Second useful sentence.
"""


class FakeTable:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.selected_columns = None
        self.upsert_payload = None
        self.upsert_called = False

    def select(self, columns):
        self.selected_columns = columns
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def gt(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    async def execute(self):
        rows = [self.upsert_payload] if self.upsert_called else self.rows
        return type("Response", (), {"data": rows})()

    def upsert(self, payload, *, on_conflict):
        self.upsert_payload = payload
        self.upsert_called = True
        return self


class FakeClient:
    def __init__(self, table):
        self._table = table

    def table(self, _name):
        return self._table


@pytest.mark.asyncio
async def test_get_cached_markdown_selects_content_cleaning():
    table = FakeTable()
    client = FakeClient(table)

    await get_cached_markdown(
        client,
        "https://example.com",
        False,
        False,
        False,
        False,
    )

    assert "content_cleaning" in table.selected_columns


@pytest.mark.asyncio
async def test_upsert_cached_markdown_writes_content_cleaning():
    table = FakeTable()
    client = FakeClient(table)
    content_cleaning = {"extractive_summary": {"applied": True}}

    await upsert_cached_markdown(
        client,
        "https://example.com",
        False,
        False,
        False,
        False,
        "# Example\n\nUseful text.",
        False,
        content_cleaning=content_cleaning,
    )

    assert table.upsert_payload["content_cleaning"] == content_cleaning


@pytest.mark.asyncio
async def test_cached_markdown_defaults_content_cleaning_to_none():
    cached = CachedMarkdown(
        markdown="# Example\n\nUseful text.",
        truncated=False,
    )

    assert cached.content_cleaning is None


@pytest.mark.asyncio
async def test_write_persistent_cache_passes_content_cleaning():
    from bintu_api.extraction.persistent_cache import write_persistent_cache

    captured = {}

    async def fake_upsert(
        *_args,
        content_cleaning=None,
        **_kwargs,
    ):
        captured["content_cleaning"] = content_cleaning

    result = CachedMarkdown(
        markdown="# Example\n\nUseful text.",
        truncated=False,
        content_cleaning={"extractive_summary": {"applied": True}},
    )

    await write_persistent_cache(
        object(),
        "https://example.com",
        False,
        False,
        False,
        False,
        result,
        fake_upsert,
    )

    assert captured["content_cleaning"] == result.content_cleaning


def test_validate_cached_summary_rejects_changed_source():
    import hashlib

    from bintu_api.extraction.summary_cache import (
        validate_cached_extractive_summary,
    )

    sentence = "First useful sentence."
    start = MARKDOWN.index(sentence)
    payload = {
        "applied": True,
        "mode": "leading",
        "requested_sentence_count": 1,
        "returned_sentence_count": 1,
        "truncated": False,
        "algorithm_version": "v1-grounded-mmr",
        "source_fingerprint": hashlib.sha256(
            MARKDOWN.encode("utf-8")
        ).hexdigest(),
        "sentences": [
            {
                "text": sentence,
                "heading_path": ["Example"],
                "char_start": start,
                "char_end": start + len(sentence),
                "score": 1.0,
            }
        ],
    }

    result = validate_cached_extractive_summary(
        MARKDOWN + "\nChanged.",
        payload,
    )

    assert result.status == "source_changed"
    assert result.summary_payload is None


def build_valid_cached_result():
    payload = {
        "applied": True,
        "mode": "leading",
        "requested_sentence_count": 1,
        "returned_sentence_count": 1,
        "truncated": False,
        "algorithm_version": "v1-grounded-mmr",
        "source_fingerprint": __import__("hashlib").sha256(
            MARKDOWN.encode("utf-8")
        ).hexdigest(),
        "sentences": [
            {
                "text": "First useful sentence.",
                "heading_path": ["Example"],
                "char_start": MARKDOWN.index("First useful sentence."),
                "char_end": MARKDOWN.index("First useful sentence.")
                + len("First useful sentence."),
                "score": 1.0,
            }
        ],
    }

    return CachedMarkdown(
        markdown=MARKDOWN,
        truncated=False,
        content_cleaning={"extractive_summary": payload},
    )


def test_validate_valid_cached_summary_returns_valid():
    from bintu_api.extraction.summary_cache import (
        validate_cached_extractive_summary,
    )

    result = build_valid_cached_result()
    payload = result.content_cleaning["extractive_summary"]

    validation = validate_cached_extractive_summary(
        result.markdown,
        payload,
    )

    assert validation.status == "valid"
    assert validation.summary_payload == payload


def test_validate_missing_cached_summary_returns_missing_metadata():
    from bintu_api.extraction.summary_cache import (
        validate_cached_extractive_summary,
    )

    result = CachedMarkdown(
        markdown=MARKDOWN,
        truncated=False,
        content_cleaning=None,
    )

    validation = validate_cached_extractive_summary(
        result.markdown,
        None,
    )

    assert validation.status == "missing_metadata"
    assert validation.summary_payload is None


def test_invalid_cached_summary_metadata_is_removed():
    import hashlib

    from bintu_api.extraction.summary_cache import (
        validate_cached_extractive_summary,
    )

    result = build_valid_cached_result()
    payload = result.content_cleaning["extractive_summary"]
    payload["source_fingerprint"] = hashlib.sha256(
        (result.markdown + "\nChanged.").encode("utf-8")
    ).hexdigest()

    validation = validate_cached_extractive_summary(
        result.markdown,
        payload,
    )

    assert validation.status == "source_changed"

    if validation.status != "valid":
        result.content_cleaning.pop("extractive_summary", None)

    assert "extractive_summary" not in result.content_cleaning
