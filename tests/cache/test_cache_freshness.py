"""Deterministic cache freshness provenance tests."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from bintu_api.extraction.memory_cache import (
    MemoryCacheEntry,
    read_memory_cache,
    write_memory_cache,
)
from bintu_api.extraction.output import build_provenance
from bintu_api.settings import Settings


class FakeMemoryCache:
    def __init__(self) -> None:
        self.items: dict[str, object] = {}

    def get(self, key: str) -> object | None:
        return self.items.get(key)

    def set(self, key: str, value: object) -> None:
        self.items[key] = value


def _settings() -> MagicMock:
    settings = MagicMock()
    settings.service_version = "test"
    return settings


def _provenance(
    *,
    cache_layer: str,
    extracted_at: str | None,
) -> object:
    return build_provenance(
        url="https://example.com",
        text="Example",
        document=None,
        cache_layer=cache_layer,
        request_id="req-test",
        settings=_settings(),
        extracted_at=extracted_at,
    )


def test_fresh_response_has_null_age() -> None:
    provenance = _provenance(
        cache_layer="none",
        extracted_at=None,
    )

    assert provenance.cache.age_seconds is None


def test_memory_hit_reports_truncated_integer_age() -> None:
    extracted_at = (
        datetime.now(UTC) - timedelta(seconds=90.7)
    ).isoformat()

    provenance = _provenance(
        cache_layer="memory",
        extracted_at=extracted_at,
    )

    assert provenance.cache.age_seconds == 90


def test_persistent_hit_reports_truncated_integer_age() -> None:
    extracted_at = (
        datetime.now(UTC) - timedelta(seconds=300.9)
    ).isoformat()

    provenance = _provenance(
        cache_layer="persistent",
        extracted_at=extracted_at,
    )

    assert provenance.cache.age_seconds == 300


def test_future_timestamp_clamps_to_zero() -> None:
    extracted_at = (
        datetime.now(UTC) + timedelta(seconds=30)
    ).isoformat()

    provenance = _provenance(
        cache_layer="persistent",
        extracted_at=extracted_at,
    )

    assert provenance.cache.age_seconds == 0


def test_unknown_and_invalid_timestamps_yield_null() -> None:
    for extracted_at in (None, "", "not-a-date"):
        provenance = _provenance(
            cache_layer="memory",
            extracted_at=extracted_at,
        )

        assert provenance.cache.age_seconds is None


def test_naive_timestamp_yields_null() -> None:
    provenance = _provenance(
        cache_layer="memory",
        extracted_at="2026-01-01T00:00:00",
    )

    assert provenance.cache.age_seconds is None


def test_z_timestamp_is_supported() -> None:
    extracted_at = (
        datetime.now(UTC) - timedelta(seconds=60)
    ).isoformat().replace("+00:00", "Z")

    provenance = _provenance(
        cache_layer="memory",
        extracted_at=extracted_at,
    )

    assert provenance.cache.age_seconds == 60


def test_non_utc_offset_is_supported() -> None:
    extracted_at = (
        datetime.now(UTC) - timedelta(seconds=120)
    ).astimezone().isoformat()

    provenance = _provenance(
        cache_layer="memory",
        extracted_at=extracted_at,
    )

    assert isinstance(provenance.cache.age_seconds, int)
    assert provenance.cache.age_seconds >= 0


def test_memory_cache_preserves_extraction_timestamp() -> None:
    cache = FakeMemoryCache()
    document = MagicMock()
    extracted_at = "2026-01-01T00:00:00+00:00"

    write_memory_cache(
        cache,
        "key",
        document,
        "none",
        "extracted text",
        extracted_at,
    )

    entry = asyncio.run(read_memory_cache(cache, "key", False, []))

    assert isinstance(entry, MemoryCacheEntry)
    assert entry.document is document
    assert entry.extracted_at == extracted_at


def test_legacy_memory_entry_remains_unknown() -> None:
    cache = FakeMemoryCache()
    document = MagicMock()
    cache.set("key", document)

    entry = asyncio.run(read_memory_cache(cache, "key", False, []))

    assert isinstance(entry, MemoryCacheEntry)
    assert entry.document is document
    assert entry.extracted_at == ""


def test_memory_cache_does_not_write_empty_extraction() -> None:
    cache = FakeMemoryCache()

    write_memory_cache(
        cache,
        "key",
        MagicMock(),
        "none",
        "   ",
        "2026-01-01T00:00:00+00:00",
    )

    assert cache.items == {}


def test_fresh_extraction_is_fresh_without_cache_age():
    settings = Settings(
        api_key="",
        rapidapi_proxy_secret="",
    )
    provenance = build_provenance(
        "https://example.com/article",
        "Meaningful content.",
        None,
        "none",
        "request-1",
        settings,
        extracted_at=None,
    )

    assert provenance.cache.hit is False
    assert provenance.cache.layer == "none"
    assert provenance.cache.age_seconds is None
    assert provenance.cache.fresh is True
