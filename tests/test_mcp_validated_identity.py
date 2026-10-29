"""MCP buckets must follow validated credentials, not arbitrary headers."""

import hashlib

from starlette.requests import Request

from bintu_api.auth import (
    mcp_rate_limit_identity,
    verify_mcp_execution_access,
)
from bintu_api.settings import Settings


IP = "203.0.113.9"
SCOPED = "test-scoped-key"
MASTER = "test-master-key"


def settings():
    return Settings(
        api_key=MASTER,
        mcp_api_key=SCOPED,
        rapidapi_proxy_secret="",
        require_auth=True,
    )


def request(headers=None):
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [
            (name.lower().encode("ascii"), value.encode("ascii"))
            for name, value in (headers or {}).items()
        ],
        "query_string": b"",
        "client": (IP, 1234),
    })


def fingerprint(key):
    return "mcp:" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def test_valid_bearer_ignores_rotating_invalid_api_key_headers():
    config = settings()
    identities = set()

    for index in range(50):
        req = request({
            "Authorization": f"Bearer {SCOPED}",
            "X-API-Key": f"invalid-key-{index}",
        })
        verify_mcp_execution_access(req, config)
        identities.add(mcp_rate_limit_identity(req, config))

    assert identities == {fingerprint(SCOPED)}


def test_invalid_credentials_share_client_ip_identity():
    config = settings()
    identities = {
        mcp_rate_limit_identity(
            request({"X-API-Key": f"invalid-key-{index}"}),
            config,
        )
        for index in range(50)
    }

    assert identities == {IP}


def test_valid_scoped_and_master_keys_keep_distinct_fingerprints():
    config = settings()

    for key in (SCOPED, MASTER):
        req = request({"X-API-Key": key})
        verify_mcp_execution_access(req, config)
        identity = mcp_rate_limit_identity(req, config)

        assert identity == fingerprint(key)
        assert key not in identity

    assert fingerprint(SCOPED) != fingerprint(MASTER)


def test_valid_bearer_identity_is_unchanged_by_invalid_api_key():
    config = settings()

    bearer_only = request({"Authorization": f"Bearer {SCOPED}"})
    mixed = request({
        "Authorization": f"Bearer {SCOPED}",
        "X-API-Key": "invalid-key",
    })

    assert (
        mcp_rate_limit_identity(bearer_only, config)
        == mcp_rate_limit_identity(mixed, config)
        == fingerprint(SCOPED)
    )
