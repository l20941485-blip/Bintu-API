import pytest

from bintu_api.reader import DocumentSnapshot
from bintu_api.reader_store import SnapshotStore, SnapshotUnavailable


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def start(store, text="x" * 100, owner="alice", budget=2):
    return store.create(
        DocumentSnapshot(text),
        owner=owner,
        max_tokens=budget,
    )


def test_continuation_reconstructs_long_document_exactly():
    text = ("Documentation paragraph.\n" * 500) + "END_MARKER"
    store = SnapshotStore(max_handles=8)
    result = start(store, text=text, budget=32)
    parts = [result.page.text]

    for _ in range(len(text)):
        assert result.page.approx_tokens <= 32

        if result.next_cursor is None:
            break

        previous_end = result.page.end_offset
        result = store.read(
            result.next_cursor,
            owner="alice",
            max_tokens=32,
        )
        assert result.page.start_offset == previous_end
        parts.append(result.page.text)
    else:
        pytest.fail("Continuation failed to terminate.")

    assert "".join(parts) == text
    assert not result.page.has_more
    assert result.next_cursor is None


@pytest.mark.parametrize("text", ["", "Short text"])
def test_completed_document_needs_no_cursor(text):
    result = start(SnapshotStore(), text=text, budget=32)

    assert result.page.text == text
    assert not result.page.has_more
    assert result.next_cursor is None


def test_wrong_owner_and_unknown_cursor_have_same_error():
    store = SnapshotStore()
    result = start(store)
    messages = []

    for cursor, owner in [
        (result.next_cursor, "bob"),
        ("unknown-handle", "alice"),
    ]:
        with pytest.raises(SnapshotUnavailable) as error:
            store.read(cursor, owner=owner, max_tokens=2)
        messages.append(str(error.value))

    assert messages == [
        "Continuation unavailable.",
        "Continuation unavailable.",
    ]

    valid = store.read(
        result.next_cursor,
        owner="alice",
        max_tokens=2,
    )
    assert valid.page.start_offset == result.page.end_offset


def test_expiry_is_fixed_and_reads_do_not_extend_it():
    clock = Clock()
    store = SnapshotStore(ttl_seconds=10, clock=clock)
    first = start(store)

    clock.advance(9)
    second = store.read(
        first.next_cursor,
        owner="alice",
        max_tokens=2,
    )

    clock.advance(1)
    for cursor in [first.next_cursor, second.next_cursor]:
        with pytest.raises(SnapshotUnavailable):
            store.read(cursor, owner="alice", max_tokens=2)


def test_document_eviction_invalidates_all_its_handles():
    store = SnapshotStore(max_documents=1)
    first = start(store)
    later = store.read(
        first.next_cursor,
        owner="alice",
        max_tokens=2,
    )
    replacement = start(store, text="y" * 100)

    for cursor in [first.next_cursor, later.next_cursor]:
        with pytest.raises(SnapshotUnavailable):
            store.read(cursor, owner="alice", max_tokens=2)

    page = store.read(
        replacement.next_cursor,
        owner="alice",
        max_tokens=2,
    )
    assert page.page.text == "y" * 8


def test_handle_capacity_evicts_oldest_handle():
    store = SnapshotStore(max_handles=1)
    first = start(store)
    second = store.read(
        first.next_cursor,
        owner="alice",
        max_tokens=2,
    )

    with pytest.raises(SnapshotUnavailable):
        store.read(first.next_cursor, owner="alice", max_tokens=2)

    third = store.read(
        second.next_cursor,
        owner="alice",
        max_tokens=2,
    )
    assert third.page.start_offset == second.page.end_offset


def test_retrying_available_cursor_returns_same_text():
    store = SnapshotStore()
    first = start(store)

    left = store.read(
        first.next_cursor,
        owner="alice",
        max_tokens=2,
    )
    right = store.read(
        first.next_cursor,
        owner="alice",
        max_tokens=2,
    )

    assert left.page == right.page
    assert left.next_cursor != right.next_cursor


def test_budget_can_change_between_pages():
    store = SnapshotStore()
    first = start(store, budget=1)
    second = store.read(
        first.next_cursor,
        owner="alice",
        max_tokens=3,
    )

    assert second.page.start_offset == first.page.end_offset
    assert second.page.text == "x" * 12
    assert second.page.approx_tokens <= 3


def test_completed_document_does_not_evict_retained_document():
    store = SnapshotStore(max_documents=1)
    first = start(store)
    complete = start(store, text="short", budget=10)

    assert complete.next_cursor is None
    result = store.read(
        first.next_cursor,
        owner="alice",
        max_tokens=2,
    )
    assert result.page.start_offset == first.page.end_offset


def test_invalid_read_budget_does_not_consume_cursor():
    store = SnapshotStore()
    first = start(store)

    with pytest.raises(ValueError):
        store.read(
            first.next_cursor,
            owner="alice",
            max_tokens=0,
        )

    result = store.read(
        first.next_cursor,
        owner="alice",
        max_tokens=2,
    )
    assert result.page.start_offset == first.page.end_offset


def test_invalid_creation_does_not_evict_document():
    store = SnapshotStore(max_documents=1)
    first = start(store)

    with pytest.raises(ValueError):
        start(store, budget=0)

    result = store.read(
        first.next_cursor,
        owner="alice",
        max_tokens=2,
    )
    assert result.page.start_offset == first.page.end_offset


@pytest.mark.parametrize("cursor", [None, 123, [], {}, ""])
def test_invalid_cursor_is_unavailable(cursor):
    with pytest.raises(SnapshotUnavailable):
        SnapshotStore().read(
            cursor,
            owner="alice",
            max_tokens=2,
        )


@pytest.mark.parametrize("owner", ["", " ", None, 123])
def test_rejects_invalid_owner(owner):
    store = SnapshotStore()

    with pytest.raises(ValueError, match="owner"):
        start(store, owner=owner)

    with pytest.raises(ValueError, match="owner"):
        store.read("unknown", owner=owner, max_tokens=2)


@pytest.mark.parametrize(
    "setting", ["ttl_seconds", "max_documents", "max_handles"]
)
@pytest.mark.parametrize("value", [0, -1, True, 1.5, "2", None])
def test_rejects_invalid_store_settings(setting, value):
    with pytest.raises(ValueError, match=setting):
        SnapshotStore(**{setting: value})


def test_rejects_non_snapshot_input():
    with pytest.raises(ValueError, match="snapshot"):
        SnapshotStore().create(
            "not a snapshot",
            owner="alice",
            max_tokens=2,
        )


def test_independent_stores_do_not_share_handles():
    first_store = SnapshotStore()
    result = start(first_store)

    with pytest.raises(SnapshotUnavailable):
        SnapshotStore().read(
            result.next_cursor,
            owner="alice",
            max_tokens=2,
        )
