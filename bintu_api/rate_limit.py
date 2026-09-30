import threading
import time
from collections import deque

from fastapi import HTTPException

from bintu_api.settings import Settings


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
                raise HTTPException(
                    status_code=429,
                    detail={
                        "code": "burst_rate_limit_exceeded",
                        "message": f"Limit is {self._limit} requests per {self._window} seconds.",
                    },
                )
            timestamps.append(now)