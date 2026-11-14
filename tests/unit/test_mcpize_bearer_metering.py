"""Focused tests for MCPize Bearer metering identity resolution."""

import unittest
from unittest.mock import Mock

from starlette.requests import Request

from bintu_api.metering.identity import _hash, resolve_metering_identity
from bintu_api.settings import Settings


class MCPizeBearerMeteringTests(unittest.TestCase):
    def _request(self, headers: dict[str, str]) -> Mock:
        request = Mock(spec=Request)
        request.headers = headers
        return request

    def test_valid_mcp_api_key_bearer_resolves_to_mcpize(self):
        settings = Settings(
            api_key="",
            rapidapi_proxy_secret="",
            mcp_api_key="mcpize-secret",
        )
        identity, gateway = resolve_metering_identity(
            self._request({"Authorization": "Bearer mcpize-secret"}),
            settings,
        )

        self.assertEqual(identity, f"mcpize:{_hash('mcpize-secret')}")
        self.assertEqual(gateway, "mcpize")

    def test_valid_master_api_key_bearer_resolves_to_mcpize(self):
        settings = Settings(
            api_key="master-secret",
            rapidapi_proxy_secret="",
            mcp_api_key="mcpize-secret",
        )
        identity, gateway = resolve_metering_identity(
            self._request({"Authorization": "Bearer master-secret"}),
            settings,
        )

        self.assertEqual(identity, f"mcpize:{_hash('master-secret')}")
        self.assertEqual(gateway, "mcpize")

    def test_bearer_scheme_is_case_insensitive(self):
        settings = Settings(
            api_key="",
            rapidapi_proxy_secret="",
            mcp_api_key="mcpize-secret",
        )
        identity, gateway = resolve_metering_identity(
            self._request({"Authorization": "bearer mcpize-secret"}),
            settings,
        )

        self.assertEqual(identity, f"mcpize:{_hash('mcpize-secret')}")
        self.assertEqual(gateway, "mcpize")

    def test_x_api_key_and_bearer_produce_same_identity(self):
        settings = Settings(
            api_key="",
            rapidapi_proxy_secret="",
            mcp_api_key="mcpize-secret",
        )

        api_key_result = resolve_metering_identity(
            self._request({"X-API-Key": "mcpize-secret"}),
            settings,
        )
        bearer_result = resolve_metering_identity(
            self._request({"Authorization": "Bearer mcpize-secret"}),
            settings,
        )

        self.assertEqual(api_key_result, bearer_result)

    def test_invalid_bearer_returns_none(self):
        settings = Settings(
            api_key="",
            rapidapi_proxy_secret="",
            mcp_api_key="mcpize-secret",
        )

        self.assertIsNone(
            resolve_metering_identity(
                self._request({"Authorization": "Bearer wrong-secret"}),
                settings,
            )
        )

    def test_local_user_id_does_not_override_valid_bearer(self):
        settings = Settings(
            api_key="",
            rapidapi_proxy_secret="",
            mcp_api_key="mcpize-secret",
        )
        identity, gateway = resolve_metering_identity(
            self._request(
                {
                    "Authorization": "Bearer mcpize-secret",
                    "x-user-id": "local-user",
                }
            ),
            settings,
        )

        self.assertEqual(identity, f"mcpize:{_hash('mcpize-secret')}")
        self.assertEqual(gateway, "mcpize")


if __name__ == "__main__":
    unittest.main()
