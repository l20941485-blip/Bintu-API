"""In-memory TTL cache for scraped HTML content."""

import threading
import time
from collections import OrderedDict
from typing import Generic, TypeVar

# Each entry can be up to 1 MiB (the scraper's hard body limit), so the entry
# count bounds memory use: 64 entries ~= 64 MiB worst case per instance.
DEFAULT_MAX_ENTRIES = 64
T = TypeVar("T")


class TTLCache(Generic[T]):
    """Thread-safe in-memory cache with per-entry expiration and a bounded size.

    Handlers run in Starlette's threadpool, so every access is guarded by a lock.
    Eviction is least-recently-used, and expired entries are dropped lazily on
    read, which keeps memory bounded without a background reaper.
    """

    def __init__(self, ttl_seconds: int, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        self._ttl = max(ttl_seconds, 0)
        self._max_entries = max(max_entries, 1)
        self._store: OrderedDict[str, tuple[T, float]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> T | None:
        """Return cached value if present and not expired, else None."""
        now = time.monotonic()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if now >= expires_at:
                del self._store[key]
                return None
            self._store.move_to_end(key)
            return value

    def set(self, key: str, value: T) -> None:
        """Store value with expiration time based on TTL, evicting oldest entries."""
        with self._lock:
            self._store[key] = (value, time.monotonic() + self._ttl)
            self._store.move_to_end(key)
            while len(self._store) > self._max_entries:
                self._store.popitem(last=False)

    def clear(self) -> None:
        """Remove all cached entries."""
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)
