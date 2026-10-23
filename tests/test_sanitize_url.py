"""Phase D tests for sanitize_url function."""
import unittest


class SanitizeUrlTests(unittest.TestCase):
    def test_sanitizes_utm_parameters(self) -> None:
        """Phase D: sanitize_url removes UTM tracking parameters."""
        from bintu_api.routes import sanitize_url
        result = sanitize_url("https://example.com/page?utm_source=google&utm_medium=organic")
        self.assertEqual(result, "https://example.com/page")

    def test_preserves_other_query_parameters(self) -> None:
        """Phase D: sanitize_url preserves non-tracking query parameters."""
        from bintu_api.routes import sanitize_url
        result = sanitize_url("https://example.com/page?session=123&lang=en")
        self.assertEqual(result, "https://example.com/page?session=123&lang=en")

    def test_sanitizes_multiple_utm_sources(self) -> None:
        """Phase D: sanitize_url removes all UTM variants."""
        from bintu_api.routes import sanitize_url
        result = sanitize_url(
            "https://example.com/page?utm_source=test&utm_campaign=summer&utm_content=banner&utm_id=123"
        )
        self.assertEqual(result, "https://example.com/page")

    def test_preserves_path_and_domain(self) -> None:
        """Phase D: sanitize_url keeps the base URL intact."""
        from bintu_api.routes import sanitize_url
        result = sanitize_url("https://subdomain.example.com/path/to/page?utm_source=test")
        self.assertEqual(result, "https://subdomain.example.com/path/to/page")

    def test_handles_no_query_string(self) -> None:
        """Phase D: sanitize_url handles URLs without query strings."""
        from bintu_api.routes import sanitize_url
        result = sanitize_url("https://example.com/page")
        self.assertEqual(result, "https://example.com/page")

    def test_handles_empty_query(self) -> None:
        """Phase D: sanitize_url handles URLs with just a question mark."""
        from bintu_api.routes import sanitize_url
        result = sanitize_url("https://example.com/page?")
        self.assertEqual(result, "https://example.com/page")