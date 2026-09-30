"""Tests for the burst guard and the Redis-backed limiter."""

import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

import bintu_api.rate_limit as rate_limit
from bintu_api.settings import Settings


class _FakePipeline:
    def __init__(self, owner: "_FakeRedis") -> None:
        self._owner = owner
        self._commands: list[str] = []

    def incr(self, key: str) -> None:
        self._commands.append("incr")
        self._owner.keys_incr.append(key)

    def ttl(self, key: str) -> None:
        self._commands.append("ttl")
        self._owner.keys_ttl.append(key)

    def execute(self) -> list[int]:
        self._owner.pipeline_commands.append(tuple(self._commands))
        return self._owner.results.pop(0)


class _FakeRedis:
    """Minimal stand-in exposing only what RedisRateLimiter calls."""

    def __init__(self, results, error: Exception | None = None) -> None:
        self.results = results
        self.error = error
        self.pipeline_commands: list[tuple[str, ...]] = []
        self.expire_calls: list[tuple[str, int]] = []
        self.keys_incr: list[str] = []
        self.keys_ttl: list[str] = []

    def pipeline(self) -> _FakePipeline:
        if self.error is not None:
            raise self.error
        return _FakePipeline(self)

    def expire(self, key: str, seconds: int) -> None:
        self.expire_calls.append((key, seconds))


class BurstRateLimiterTests(unittest.TestCase):
    def _settings(self, limit: int = 2) -> Settings:
        return Settings(
            api_key="",
            rapidapi_proxy_secret="",
            rate_limit_requests=limit,
            rate_limit_window_seconds=60,
        )

    def test_allows_limit_then_rejects_with_retry_after(self) -> None:
        limiter = rate_limit.BurstRateLimiter(self._settings())
        limiter.check("client-a")
        limiter.check("client-a")

        with self.assertRaises(HTTPException) as raised:
            limiter.check("client-a")

        self.assertEqual(raised.exception.status_code, 429)
        self.assertEqual(raised.exception.detail["code"], "burst_rate_limit_exceeded")
        self.assertIn("Retry-After", raised.exception.headers)
        self.assertGreaterEqual(int(raised.exception.headers["Retry-After"]), 1)

    def test_buckets_are_per_identity(self) -> None:
        limiter = rate_limit.BurstRateLimiter(self._settings())
        limiter.check("client-a")
        limiter.check("client-a")

        limiter.check("client-b")  # must not be blocked by client-a's traffic


class RedisRateLimiterTests(unittest.TestCase):
    def _settings(self, limit: int = 2) -> Settings:
        return Settings(
            api_key="",
            rapidapi_proxy_secret="",
            rate_limit_requests=limit,
            rate_limit_window_seconds=60,
        )

    def _build(self, fake_redis: _FakeRedis, limit: int = 2) -> rate_limit.RedisRateLimiter:
        redis_module = MagicMock()
        redis_module.from_url.return_value = fake_redis
        with patch.object(rate_limit, "redis", redis_module):
            return rate_limit.RedisRateLimiter("redis://cache.example:6379/0", self._settings(limit))

    def test_window_ttl_is_applied_only_until_the_key_has_one(self) -> None:
        fake = _FakeRedis(results=[[1, -1], [2, 42], [3, 41]])
        limiter = self._build(fake, limit=5)

        limiter.check("client-a")  # fresh key: Redis reports no TTL (-1)
        limiter.check("client-a")  # TTL already running: must not be reset
        limiter.check("client-a")

        self.assertEqual(fake.expire_calls, [("rate_limit:client-a", 60)])
        self.assertEqual(fake.pipeline_commands, [("incr", "ttl")] * 3)

    def test_over_limit_sets_retry_after_from_remaining_ttl(self) -> None:
        fake = _FakeRedis(results=[[3, 17]])
        limiter = self._build(fake)

        with self.assertRaises(HTTPException) as raised:
            limiter.check("client-a")

        self.assertEqual(raised.exception.status_code, 429)
        self.assertEqual(raised.exception.headers["Retry-After"], "17")

    def test_redis_outage_fails_open_to_the_in_process_guard(self) -> None:
        fake = _FakeRedis(results=[], error=ConnectionError("redis is down"))
        limiter = self._build(fake)

        limiter.check("client-a")  # would have been a 500 before the fail-open path
        limiter.check("client-a")  # circuit is open: only the in-process guard runs

        with self.assertRaises(HTTPException) as raised:
            limiter.check("client-a")

        self.assertEqual(raised.exception.status_code, 429)
        self.assertEqual(fake.pipeline_commands, [])  # no further Redis traffic attempted


if __name__ == "__main__":
    unittest.main(verbosity=2)
