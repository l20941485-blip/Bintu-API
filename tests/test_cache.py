"""Tests for the bounded, thread-safe TTL cache."""

import threading
import unittest

from bintu_api.cache import TTLCache


class TTLCacheTests(unittest.TestCase):
    def test_returns_stored_value(self) -> None:
        cache = TTLCache(ttl_seconds=60)
        cache.set("key", b"payload")

        self.assertEqual(cache.get("key"), b"payload")

    def test_zero_ttl_never_returns_a_value(self) -> None:
        cache = TTLCache(ttl_seconds=0)
        cache.set("key", b"payload")

        self.assertIsNone(cache.get("key"))
        self.assertEqual(len(cache), 0)

    def test_size_is_bounded_with_least_recently_used_eviction(self) -> None:
        cache = TTLCache(ttl_seconds=60, max_entries=2)
        cache.set("a", b"1")
        cache.set("b", b"2")
        cache.get("a")  # reading 'a' makes 'b' the least recently used entry
        cache.set("c", b"3")

        self.assertEqual(len(cache), 2)
        self.assertEqual(cache.get("a"), b"1")
        self.assertIsNone(cache.get("b"))
        self.assertEqual(cache.get("c"), b"3")

    def test_expired_entry_is_removed_instead_of_raising(self) -> None:
        cache = TTLCache(ttl_seconds=60)
        cache.set("key", b"payload")
        cache._store["key"] = (b"payload", 0.0)  # force the entry into the past

        self.assertIsNone(cache.get("key"))
        self.assertEqual(len(cache), 0)
        self.assertIsNone(cache.get("key"))  # second read must not KeyError

    def test_concurrent_reads_and_writes_do_not_raise(self) -> None:
        cache = TTLCache(ttl_seconds=60, max_entries=8)
        failures: list[BaseException] = []

        def worker(index: int) -> None:
            try:
                for step in range(300):
                    cache.set(f"k{(index + step) % 20}", b"x")
                    cache.get(f"k{step % 20}")
            except BaseException as error:  # pragma: no cover - defensive
                failures.append(error)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(failures, [])
        self.assertLessEqual(len(cache), 8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
