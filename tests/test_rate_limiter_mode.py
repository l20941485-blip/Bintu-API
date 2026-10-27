from unittest.mock import patch

import pytest
from fastapi import HTTPException

from bintu_api.rate_limit import (
    RATE_LIMITER_MODE,
    BurstRateLimiter,
    RedisRateLimiter,
    create_rate_limiter,
)
from bintu_api.settings import Settings


def settings(redis_url: str = "") -> Settings:
    return Settings(
        api_key="test-key",
        rapidapi_proxy_secret="test-proxy",
        require_auth=True,
        rate_limit_requests=2,
        redis_url=redis_url,
    )


def gauge_value() -> float:
    return RATE_LIMITER_MODE._value.get()


class FailingRedis:
    class Pipeline:
        def incr(self, key):
            raise OSError("redis unavailable")

        def ttl(self, key):
            raise OSError("redis unavailable")

        def execute(self):
            raise OSError("redis unavailable")

    def pipeline(self):
        return self.Pipeline()


class WorkingRedis:
    def __init__(self):
        self.values = {}

    class Pipeline:
        def __init__(self, values):
            self.values = values
            self.key = None

        def incr(self, key):
            self.key = key
            self.values[key] = self.values.get(key, 0) + 1

        def ttl(self, key):
            return 60

        def execute(self):
            return [self.values[self.key], 60]

    def pipeline(self):
        return self.Pipeline(self.values)


def test_local_limiter_reports_fallback_mode():
    limiter = create_rate_limiter(settings())
    assert isinstance(limiter, BurstRateLimiter)
    assert gauge_value() == 0


def test_redis_limiter_reports_redis_mode():
    with patch("bintu_api.rate_limit.redis.from_url", return_value=WorkingRedis()):
        limiter = create_rate_limiter(settings("redis://localhost:6379/0"))

    assert isinstance(limiter, RedisRateLimiter)
    assert gauge_value() == 1


def test_redis_failure_reports_fallback_mode_and_uses_local_guard():
    with patch(
        "bintu_api.rate_limit.redis.from_url",
        return_value=FailingRedis(),
    ):
        limiter = create_rate_limiter(settings("redis://localhost:6379/0"))

    assert gauge_value() == 1
    limiter.check("caller")

    assert gauge_value() == 0
    assert limiter._circuit_open_until > 0

    limiter.check("caller")
    with pytest.raises(HTTPException) as error:
        limiter.check("caller")

    assert error.value.status_code == 429
    assert gauge_value() == 0
