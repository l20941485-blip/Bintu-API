"""Tests for the cosmetic-independent content fingerprint."""

from bintu_api.extraction.fingerprint import compute_content_fingerprint


def test_fingerprint_ignores_whitespace_and_case():
    first = compute_content_fingerprint("Hello  World\n\nSecond paragraph.")
    second = compute_content_fingerprint("hello world\nsecond paragraph.")

    assert first == second


def test_fingerprint_changes_when_meaningful_content_changes():
    first = compute_content_fingerprint("First meaningful paragraph.")
    second = compute_content_fingerprint("Second meaningful paragraph.")

    assert first != second


def test_fingerprint_is_sha256_prefixed():
    fingerprint = compute_content_fingerprint("Example content")

    assert fingerprint.startswith("sha256:")
    assert len(fingerprint) == len("sha256:") + 64
