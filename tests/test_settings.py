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
            {"SUPABASE_URL": " https://project.supabase.co/ ", "SUPABASE_ANON_KEY": " anon "}
        )

        self.assertEqual(settings.supabase_url, "https://project.supabase.co")
        self.assertEqual(settings.supabase_anon_key, "anon")


if __name__ == "__main__":
    unittest.main(verbosity=2)
