"""MCP credential fingerprints must isolate callers without leaking secrets."""

from __future__ import annotations

import hashlib
import unittest
from unittest.mock import MagicMock

from bintu_api.auth import mcp_rate_limit_identity
from bintu_api.settings import Settings


class McpIdentityIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            api_key="mcp-key-two",
            rapidapi_proxy_secret="",
            mcp_api_key="mcp-key-one",
        )
        self.request = MagicMock()
        self.request.headers.get.side_effect = (
            lambda name, default=None: default if default is not None else ""
        )
        self.request.client = None

    def _identity_for_credential(self, credential: str) -> str:
        self.request.headers.get.side_effect = (
            lambda name, default=None: credential
            if name == "X-API-Key"
            else (default if default is not None else "")
        )
        return mcp_rate_limit_identity(self.request, self.settings)

    def test_distinct_keys_receive_distinct_buckets(self) -> None:
        first = self._identity_for_credential("mcp-key-one")
        second = self._identity_for_credential("mcp-key-two")

        self.assertNotEqual(first, second)
        self.assertTrue(first.startswith("mcp:"))
        self.assertTrue(second.startswith("mcp:"))

    def test_identity_uses_expected_key_fingerprint(self) -> None:
        credential = "mcp-key-one"
        expected = hashlib.sha256(credential.encode("utf-8")).hexdigest()[:16]

        identity = self._identity_for_credential(credential)

        self.assertEqual(identity, f"mcp:{expected}")

    def test_raw_credential_is_not_exposed(self) -> None:
        credential = "super-secret-mcp-key"
        self.settings = Settings(
            api_key="",
            rapidapi_proxy_secret="",
            mcp_api_key=credential,
        )

        identity = self._identity_for_credential(credential)

        self.assertTrue(identity.startswith("mcp:"))
        self.assertNotIn(credential, identity)
        self.assertNotIn("secret", identity)

    def test_missing_credential_falls_back_to_client_ip(self) -> None:
        self.request.client = MagicMock()
        self.request.client.host = "203.0.113.7"

        identity = mcp_rate_limit_identity(self.request, self.settings)

        self.assertEqual(identity, "203.0.113.7")

    def test_missing_client_and_credential_uses_unknown(self) -> None:
        identity = mcp_rate_limit_identity(self.request, self.settings)

        self.assertEqual(identity, "unknown")


if __name__ == "__main__":
    unittest.main(verbosity=2)
