import logging
import math
import threading
import time
from collections import deque

from fastapi import HTTPException
from prometheus_client import Gauge

from bintu_api.settings import Settings

try:
    import redis
except ImportError:
    redis = None  # type: ignore[assignment]


logger = logging.getLogger("bintu_api.rate_limit")

RATE_LIMITER_MODE = Gauge(
    "bintu_rate_limiter_mode",
    "Active rate-limiter mode: 1 for Redis-backed, 0 for process-local fallback.",
)


class BurstRateLimiter:
    """Per-process abuse guard; RapidAPI owns paid-plan quota enforcement."""

    def __init__(self, settings: Settings) -> None:
        self._limit = settings.rate_limit_requests
        self._window = settings.rate_limit_window_seconds
        self._buckets: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._last_cleanup = 0.0

    def check(self, identity: str) -> None:
        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            if now - self._last_cleanup >= self._window:
                for client, timestamps in tuple(self._buckets.items()):
                    while timestamps and timestamps[0] <= cutoff:
                        timestamps.popleft()
                    if not timestamps:
                        del self._buckets[client]
                self._last_cleanup = now

            timestamps = self._buckets.setdefault(identity, deque())
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()
            if len(timestamps) >= self._limit:
                oldest = timestamps[0] if timestamps else now
                retry_after = max(1, math.ceil(oldest + self._window - now))
                raise HTTPException(
                    status_code=429,
                    detail={
                        "code": "burst_rate_limit_exceeded",
                        "message": f"Limit is {self._limit} requests per {self._window} seconds.",
                    },
                    headers={"Retry-After": str(retry_after)},
                )
            timestamps.append(now)


class RedisRateLimiter:
    """Redis-backed rate limiter for multi-instance deployments.

    Two behaviours matter for correctness:

    * The window TTL is (re)applied only while the key has none, so a client
      that keeps retrying cannot keep extending its own window and stay locked
      out forever.
    * Redis failures degrade to the in-process guard instead of turning an
      infrastructure outage into a 500 on every request.
    """

    CIRCUIT_OPEN_SECONDS = 30.0

    def __init__(self, redis_url: str, settings: Settings) -> None:
        if redis is None:
            raise RuntimeError("redis package is required for RedisRateLimiter")
        self._redis = redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
        self._limit = settings.rate_limit_requests
        self._window = settings.rate_limit_window_seconds
        self._fallback = BurstRateLimiter(settings)
        self._circuit_open_until = 0.0

    def check(self, identity: str) -> None:
        now = time.monotonic()
        if now < self._circuit_open_until:
            self._fallback.check(identity)
            return

        try:
            key = f"rate_limit:{identity}"
            pipe = self._redis.pipeline()
            pipe.incr(key)
            pipe.ttl(key)
            count, ttl = pipe.execute()[:2]
            if ttl is None or ttl < 0:
                self._redis.expire(key, self._window)
                ttl = self._window
        except Exception as error:  # redis.RedisError plus transport errors
            logger.warning("redis_rate_limiter_unavailable error_type=%s", type(error).__name__)
            self._circuit_open_until = now + self.CIRCUIT_OPEN_SECONDS
            RATE_LIMITER_MODE.set(0)
            self._fallback.check(identity)
            return

        RATE_LIMITER_MODE.set(1)

        if count > self._limit:
            retry_after = ttl if isinstance(ttl, int) and ttl > 0 else self._window
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "burst_rate_limit_exceeded",
                    "message": f"Limit is {self._limit} requests per {self._window} seconds.",
                },
                headers={"Retry-After": str(max(1, int(retry_after)))},
            )


def create_rate_limiter(settings: Settings):
    """Factory function to create the appropriate rate limiter."""
    if settings.redis_url and redis is not None:
        limiter = RedisRateLimiter(settings.redis_url, settings)
        RATE_LIMITER_MODE.set(1)
        return limiter
    RATE_LIMITER_MODE.set(0)
    return BurstRateLimiter(settings)
