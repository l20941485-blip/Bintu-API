"""Regression tests for numeric IP URL forms."""

from unittest.mock import patch

import pytest

from bintu_api.scraper.fetcher import (
    TargetURLRejected,
    _check_numeric_ip_safety,
    _is_numeric_ip_host,
    _normalize_host_for_ssrf,
    _normalize_numeric_ip,
    fetch_html_document,
)
from bintu_api.settings import Settings


def _settings() -> Settings:
    return Settings(api_key="", rapidapi_proxy_secret="")


class TestNormalizeNumericIP:
    """Tests for _normalize_numeric_ip function."""

    def test_decimal_integer_form(self):
        """Decimal integer form 2130706433 should normalize to 127.0.0.1."""
        assert _normalize_numeric_ip("2130706433") == "127.0.0.1"

    def test_octal_form_is_ambiguous(self):
        """A leading-zero octet form is ambiguous and is retained for rejection."""
        assert _normalize_numeric_ip("0177.0.0.1") == "0177.0.0.1"

    def test_standard_ipv4_not_numeric(self):
        """Standard IPv4 form should not be normalized."""
        assert _normalize_numeric_ip("127.0.0.1") is None

    def test_127_1_is_ambiguous(self):
        """127.1 is a shortened dotted form and is treated as ambiguous."""
        assert _normalize_numeric_ip("127.1") == "127.1"

    def test_localhost_not_numeric(self):
        """localhost should not be treated as numeric IP."""
        assert _normalize_numeric_ip("localhost") is None

    def test_ipv6_not_numeric(self):
        """IPv6 form [::1] should not be treated as numeric IP."""
        assert _normalize_numeric_ip("[::1]") is None

    def test_other_numeric_forms(self):
        """Other numeric forms should not normalize."""
        assert _normalize_numeric_ip("999.999.999.999") is None
        assert _normalize_numeric_ip("abc") is None


class TestIsNumericIPHost:
    """Tests for _is_numeric_ip_host function."""

    def test_decimal_integer_is_numeric(self):
        assert _is_numeric_ip_host("2130706433") is True

    def test_octal_form_is_numeric(self):
        assert _is_numeric_ip_host("0177.0.0.1") is True

    def test_standard_ipv4_not_numeric(self):
        assert _is_numeric_ip_host("127.0.0.1") is False

    def test_localhost_not_numeric(self):
        assert _is_numeric_ip_host("localhost") is False


class TestNormalizeHostForSSRF:
    """Tests for _normalize_host_for_ssrf function."""

    def test_decimal_integer_url(self):
        """http://2130706433/ should normalize to 127.0.0.1."""
        result = _normalize_host_for_ssrf("http://2130706433/")
        assert result == "127.0.0.1"

    def test_octal_url_is_ambiguous(self):
        """A leading-zero octet URL is ambiguous and is retained for rejection."""
        result = _normalize_host_for_ssrf("http://0177.0.0.1/")
        assert result == "0177.0.0.1"

    def test_standard_loopback_not_normalized(self):
        """http://127.0.0.1/ should not be normalized."""
        result = _normalize_host_for_ssrf("http://127.0.0.1/")
        assert result is None

    def test_localhost_not_normalized(self):
        """http://localhost/ should not be normalized."""
        result = _normalize_host_for_ssrf("http://localhost/")
        assert result is None

    def test_public_url_not_normalized(self):
        """http://example.com/ should not be normalized."""
        result = _normalize_host_for_ssrf("http://example.com/")
        assert result is None


class TestCheckNumericIPSafety:
    """Tests for _check_numeric_ip_safety function."""

    def test_2130706433_rejected(self):
        """http://2130706433/ should be rejected as invalid_or_unsafe_url."""
        s = _settings()
        rejected, error = _check_numeric_ip_safety("http://2130706433/", s)
        assert rejected is True
        assert error == "invalid_or_unsafe_url"

    def test_0177_0_0_1_rejected(self):
        """http://0177.0.0.1/ should be rejected as invalid_or_unsafe_url."""
        s = _settings()
        rejected, error = _check_numeric_ip_safety("http://0177.0.0.1/", s)
        assert rejected is True
        assert error == "invalid_or_unsafe_url"

    def test_127_0_0_1_rejected(self):
        """http://127.0.0.1/ should be rejected as invalid_or_unsafe_url."""
        s = _settings()
        rejected, error = _check_numeric_ip_safety("http://127.0.0.1/", s)
        assert rejected is True
        assert error == "invalid_or_unsafe_url"

    def test_127_1_rejected(self):
        """http://127.1/ is an ambiguous shorthand and is rejected early."""
        s = _settings()
        rejected, error = _check_numeric_ip_safety("http://127.1/", s)
        assert rejected is True
        assert error == "invalid_or_unsafe_url"

    def test_localhost_allowed(self):
        """http://localhost/ should be allowed (not a numeric IP)."""
        s = _settings()
        rejected, error = _check_numeric_ip_safety("http://localhost/", s)
        assert rejected is False
        assert error is None

    def test_example_com_allowed(self):
        """http://example.com/ should be allowed."""
        s = _settings()
        rejected, error = _check_numeric_ip_safety("http://example.com/", s)
        assert rejected is False
        assert error is None

    def test_public_dns_allowed(self):
        """Public DNS names should be allowed."""
        s = _settings()
        rejected, error = _check_numeric_ip_safety("http://8.8.8.8/", s)
        # 8.8.8.8 is a public DNS address, not loopback/private, so should be allowed
        assert rejected is False
        assert error is None


class TestAmbiguousNumericForms:
    """Ambiguous numeric forms must be rejected before network access."""

    @pytest.mark.parametrize(
        "url",
        [
            "http://134744072/",
            "http://018.0.0.1/",
            "http://4294967296/",
            "http://127.1/",
        ],
    )
    def test_ambiguous_numeric_forms_are_rejected(self, url: str):
        rejected, error = _check_numeric_ip_safety(url, _settings())
        assert rejected is True
        assert error == "invalid_or_unsafe_url"

    @pytest.mark.parametrize(
        "url",
        [
            "http://134744072/",
            "http://018.0.0.1/",
            "http://4294967296/",
            "http://127.1/",
        ],
    )
    def test_ambiguous_numeric_forms_never_reach_network(self, url: str):
        with (
            patch("bintu_api.scraper.fetcher.socket.getaddrinfo") as getaddrinfo,
            patch("bintu_api.scraper.fetcher._make_connection") as connect,
            pytest.raises(TargetURLRejected),
        ):
            fetch_html_document(url, _settings())

        getaddrinfo.assert_not_called()
        connect.assert_not_called()


class TestFetchRejectsNumericIpBeforeNetwork:
    """Decimal and dotted-octal loopback must fail before any request."""

    @pytest.mark.parametrize(
        "url",
        ["http://2130706433/", "http://0177.0.0.1/"],
    )
    def test_rejected_before_dns_or_connection(self, url: str):
        with (
            patch("bintu_api.scraper.fetcher.socket.getaddrinfo") as getaddrinfo,
            patch("bintu_api.scraper.fetcher._make_connection") as connect,
            pytest.raises(TargetURLRejected),
        ):
            fetch_html_document(url, _settings())

        getaddrinfo.assert_not_called()
        connect.assert_not_called()