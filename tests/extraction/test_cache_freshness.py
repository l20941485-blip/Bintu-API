"""Tests for cache freshness decisions and timestamp handling."""

from datetime import UTC, datetime, timedelta

from bintu_api.extraction.cache_store import CACHE_TTL
from bintu_api.extraction.output import _cache_age_seconds, build_provenance
from bintu_api.settings import Settings


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


def test_recent_cache_hit_is_fresh():
    now = datetime.now(UTC)
    extracted_at = (now - timedelta(seconds=30)).isoformat()

    assert _cache_age_seconds(extracted_at, now) == 30


def test_cache_hit_within_ttl_is_fresh():
    settings = Settings(
        api_key="",
        rapidapi_proxy_secret="",
    )
    now = datetime.now(UTC)
    extracted_at = (now - timedelta(seconds=30)).isoformat()

    provenance = build_provenance(
        "https://example.com/article",
        "Meaningful content.",
        None,
        "memory",
        "request-1",
        settings,
        extracted_at=extracted_at,
    )

    assert provenance.cache.hit is True
    assert provenance.cache.layer == "memory"
    assert provenance.cache.age_seconds == 30
    assert provenance.cache.fresh is True


def test_cache_hit_beyond_ttl_is_not_fresh():
    settings = Settings(
        api_key="",
        rapidapi_proxy_secret="",
    )
    now = datetime.now(UTC)
    extracted_at = (now - CACHE_TTL - timedelta(seconds=1)).isoformat()

    provenance = build_provenance(
        "https://example.com/article",
        "Meaningful content.",
        None,
        "memory",
        "request-1",
        settings,
        extracted_at=extracted_at,
    )

    assert provenance.cache.fresh is False


def test_future_timestamp_has_zero_age_and_is_fresh():
    now = datetime.now(UTC)
    extracted_at = (now + timedelta(seconds=30)).isoformat()

    assert _cache_age_seconds(extracted_at, now) == 0


def test_missing_or_invalid_timestamp_has_unknown_age():
    assert _cache_age_seconds(None, datetime.now(UTC)) is None
    assert _cache_age_seconds("", datetime.now(UTC)) is None
    assert _cache_age_seconds("not-a-timestamp", datetime.now(UTC)) is None
