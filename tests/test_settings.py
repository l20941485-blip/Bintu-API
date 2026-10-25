"""Tests for environment-driven configuration."""

import unittest
from unittest.mock import patch

from bintu_api.settings import Settings


class SettingsFromEnvTests(unittest.TestCase):
    def _from_env(self, environ: dict[str, str]) -> Settings:
        base = {
            "API_KEY": "",
            "RAPIDAPI_PROXY_SECRET": "",
            "SUPABASE_URL": "",
            "SUPABASE_ANON_KEY": "",
            "SUPABASE_SERVICE_ROLE_KEY": "",
            "REDIS_URL": "",
        }
        base.update(environ)
        with patch.dict("os.environ", base, clear=True):
            return Settings.from_env()

    def test_missing_value_uses_default(self) -> None:
        self.assertEqual(self._from_env({}).cache_ttl_seconds, 300)

    def test_valid_override_is_applied(self) -> None:
        self.assertEqual(self._from_env({"CACHE_TTL_SECONDS": "60"}).cache_ttl_seconds, 60)

    def test_non_numeric_value_falls_back_instead_of_crashing_startup(self) -> None:
        self.assertEqual(self._from_env({"CACHE_TTL_SECONDS": "five"}).cache_ttl_seconds, 300)

    def test_negative_value_falls_back(self) -> None:
        self.assertEqual(self._from_env({"CACHE_TTL_SECONDS": "-5"}).cache_ttl_seconds, 300)

    def test_over_range_value_falls_back(self) -> None:
        self.assertEqual(self._from_env({"CACHE_TTL_SECONDS": "999999"}).cache_ttl_seconds, 300)

    def test_zero_ttl_is_accepted_as_an_explicit_opt_out(self) -> None:
        self.assertEqual(self._from_env({"CACHE_TTL_SECONDS": "0"}).cache_ttl_seconds, 0)

    def test_secrets_are_trimmed(self) -> None:
        settings = self._from_env({"API_KEY": "  secret  ", "RAPIDAPI_PROXY_SECRET": " proxy "})

        self.assertEqual(settings.api_key, "secret")
        self.assertEqual(settings.rapidapi_proxy_secret, "proxy")

    def test_supabase_configuration_is_trimmed(self) -> None:
        settings = self._from_env(
            {
                "SUPABASE_URL": " https://project.supabase.co/ ",
                "SUPABASE_ANON_KEY": " anon ",
                "SUPABASE_SERVICE_ROLE_KEY": " service-role ",
            }
        )

        self.assertEqual(settings.supabase_url, "https://project.supabase.co")
        self.assertEqual(settings.supabase_anon_key, "anon")
        self.assertEqual(settings.supabase_service_role_key, "service-role")

    def test_render_js_is_disabled_by_default(self) -> None:
        self.assertFalse(self._from_env({}).render_js_enabled)

    def test_render_js_requires_explicit_true(self) -> None:
        self.assertTrue(self._from_env({"RENDER_JS_ENABLED": "true"}).render_js_enabled)
        self.assertTrue(self._from_env({"RENDER_JS_ENABLED": " True "}).render_js_enabled)
        self.assertFalse(self._from_env({"RENDER_JS_ENABLED": "1"}).render_js_enabled)
        self.assertFalse(self._from_env({"RENDER_JS_ENABLED": "yes"}).render_js_enabled)
        self.assertFalse(self._from_env({"RENDER_JS_ENABLED": "false"}).render_js_enabled)

    def test_require_auth_is_disabled_by_default(self) -> None:
        self.assertFalse(self._from_env({}).require_auth)

    def test_require_auth_requires_explicit_true(self) -> None:
        self.assertTrue(self._from_env({"REQUIRE_AUTH": "true"}).require_auth)
        self.assertTrue(self._from_env({"REQUIRE_AUTH": " True "}).require_auth)
        self.assertFalse(self._from_env({"REQUIRE_AUTH": "1"}).require_auth)
        self.assertFalse(self._from_env({"REQUIRE_AUTH": "yes"}).require_auth)
        self.assertFalse(self._from_env({"REQUIRE_AUTH": "false"}).require_auth)


def test_service_version_is_1_1_0(self) -> None:
    """Phase D: service_version must be 1.1.0 after version bump."""
    settings = self._from_env({})
    self.assertEqual(settings.service_version, "1.1.0")

if __name__ == "__main__":
    unittest.main(verbosity=2)
