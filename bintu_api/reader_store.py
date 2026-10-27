"""Bounded process-local snapshots and caller-bound continuation handles."""

import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable

from bintu_api.reader import DocumentPage, DocumentSnapshot, read_page


class SnapshotUnavailable(ValueError):
    """Unknown, expired, evicted, or inaccessible continuation."""


@dataclass(frozen=True)
class StoredPage:
    page: DocumentPage
    next_cursor: str | None


@dataclass(frozen=True)
class _Entry:
    snapshot: DocumentSnapshot
    owner: str
    expires_at: float


class SnapshotStore:
    """Fixed-lifetime snapshots with bounded, opaque continuation handles.

    Caller identities must come from trusted authentication, not request
    arguments. Handles contain no document text, URLs, or caller identities.
    Reads do not extend snapshot lifetime. State is lost on process restart.
    """

    def __init__(
        self,
        *,
        ttl_seconds: int = 600,
        max_documents: int = 16,
        max_handles: int = 256,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        for name, value in (
            ("ttl_seconds", ttl_seconds),
            ("max_documents", max_documents),
            ("max_handles", max_handles),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 1
            ):
                raise ValueError(f"{name} must be a positive integer.")

        self._ttl = ttl_seconds
        self._max_documents = max_documents
        self._max_handles = max_handles
        self._clock = clock
        self._documents: OrderedDict[str, _Entry] = OrderedDict()
        self._handles: OrderedDict[str, tuple[str, int]] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def _validate_owner(owner: str) -> None:
        if not isinstance(owner, str) or not owner.strip():
            raise ValueError("owner must be a nonempty string.")

    def _drop_document(self, document_id: str) -> None:
        self._documents.pop(document_id, None)
        stale = [
            cursor
            for cursor, (stored_id, _) in self._handles.items()
            if stored_id == document_id
        ]
        for cursor in stale:
            del self._handles[cursor]

    def _purge_expired(self, now: float) -> None:
        expired = [
            document_id
            for document_id, entry in self._documents.items()
            if now >= entry.expires_at
        ]
        for document_id in expired:
            self._drop_document(document_id)

    def _new_identifier(self) -> str:
        while True:
            value = secrets.token_urlsafe(32)
            if value not in self._documents and value not in self._handles:
                return value

    def _wrap_page(
        self, document_id: str, page: DocumentPage
    ) -> StoredPage:
        cursor = None
        if page.next_offset is not None:
            cursor = self._new_identifier()
            self._handles[cursor] = (document_id, page.next_offset)
            while len(self._handles) > self._max_handles:
                self._handles.popitem(last=False)
        return StoredPage(page=page, next_cursor=cursor)

    def create(
        self,
        snapshot: DocumentSnapshot,
        *,
        owner: str,
        max_tokens: int,
    ) -> StoredPage:
        """Retain a snapshot only when the first page needs continuation."""
        self._validate_owner(owner)
        if not isinstance(snapshot, DocumentSnapshot):
            raise ValueError("snapshot must be a DocumentSnapshot.")

        page = read_page(snapshot, max_tokens=max_tokens)

        with self._lock:
            now = self._clock()
            self._purge_expired(now)

            if not page.has_more:
                return StoredPage(page=page, next_cursor=None)

            while len(self._documents) >= self._max_documents:
                oldest_id = next(iter(self._documents))
                self._drop_document(oldest_id)

            document_id = self._new_identifier()
            self._documents[document_id] = _Entry(
                snapshot=snapshot,
                owner=owner,
                expires_at=now + self._ttl,
            )
            return self._wrap_page(document_id, page)

    def read(
        self,
        cursor: str,
        *,
        owner: str,
        max_tokens: int,
    ) -> StoredPage:
        """Read a caller-owned continuation without refetching any URL."""
        self._validate_owner(owner)

        with self._lock:
            self._purge_expired(self._clock())

            position = (
                self._handles.get(cursor)
                if isinstance(cursor, str)
                else None
            )
            if position is None:
                raise SnapshotUnavailable("Continuation unavailable.")

            document_id, offset = position
            entry = self._documents.get(document_id)
            if entry is None or entry.owner != owner:
                raise SnapshotUnavailable("Continuation unavailable.")

            page = read_page(
                entry.snapshot,
                max_tokens=max_tokens,
                offset=offset,
            )
            return self._wrap_page(document_id, page)
