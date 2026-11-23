"""Phase D tests for Provenance model and CacheInfo."""

import unittest
from datetime import UTC, datetime

from bintu_api.api.schemas import CacheInfo, Provenance


class ProvenanceTests(unittest.TestCase):
    def test_provenance_creation(self) -> None:
        """Phase D: Provenance model creates successfully with all fields."""
        provenance = Provenance(
            request_id="req-123",
            fetched_at=datetime.now(UTC).isoformat(),
            requested_url="https://example.com",
            final_url="https://example.com",
            canonical_url=None,
            upstream_status=200,
            redirect_count=0,
            content_type="text/html",
            bytes_fetched=1234,
            content_sha256="abc123",
            cache=CacheInfo(hit=False, layer="memory", age_seconds=0),
            extractor_version="1.1.0",
        )
        self.assertEqual(provenance.request_id, "req-123")
        self.assertEqual(provenance.content_sha256, "abc123")
        self.assertEqual(provenance.upstream_status, 200)
        self.assertEqual(provenance.redirect_count, 0)

    def test_provenance_with_cache_hit(self) -> None:
        """Phase D: Provenance with cache hit metadata."""
        provenance = Provenance(
            request_id="req-456",
            fetched_at=datetime.now(UTC).isoformat(),
            requested_url="https://example.com",
            final_url="https://example.com",
            canonical_url=None,
            upstream_status=200,
            redirect_count=1,
            content_type="application/json",
            bytes_fetched=500,
            content_sha256="def456",
            cache=CacheInfo(hit=True, layer="persistent", age_seconds=300),
            extractor_version="1.1.0",
        )
        self.assertTrue(provenance.cache.hit)
        self.assertEqual(provenance.cache.layer, "persistent")
        self.assertEqual(provenance.cache.age_seconds, 300)
        self.assertEqual(provenance.redirect_count, 1)

    def test_cache_info_minimal(self) -> None:
        """Phase D: CacheInfo requires all fields."""
        cache = CacheInfo(hit=False, layer="memory", age_seconds=0)
        self.assertFalse(cache.hit)
        self.assertEqual(cache.layer, "memory")
        self.assertEqual(cache.age_seconds, 0)




def test_build_provenance_includes_language_when_available():
    from unittest.mock import MagicMock

    from bintu_api.common.fetch import FetchedHTML
    from bintu_api.extraction.output import build_provenance

    document = FetchedHTML(
        body=b"<html lang=\"en\"><body>Example</body></html>",
        charset="utf-8",
        final_url="https://example.com/",
        status=200,
        redirect_count=0,
        content_type="text/html; charset=utf-8",
        language="en",
    )

    provenance = build_provenance(
        "https://example.com/",
        "Example",
        document,
        "none",
        "request-1",
        MagicMock(service_version="test"),
    )

    assert provenance.language == "en"


def test_build_provenance_omits_language_when_unavailable():
    from unittest.mock import MagicMock

    from bintu_api.common.fetch import FetchedHTML
    from bintu_api.extraction.output import build_provenance

    document = FetchedHTML(
        body=b"<html><body>Example</body></html>",
        charset="utf-8",
        final_url="https://example.com/",
        status=200,
        redirect_count=0,
        content_type="text/html; charset=utf-8",
    )

    provenance = build_provenance(
        "https://example.com/",
        "Example",
        document,
        "none",
        "request-1",
        MagicMock(service_version="test"),
    )

    assert provenance.language is None
