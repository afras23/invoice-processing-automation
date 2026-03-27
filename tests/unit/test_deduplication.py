"""
Unit tests for the deduplication service.
"""

from app.services.deduplication import DeduplicationStore, compute_hash


def test_hash_is_64_hex_characters():
    h = compute_hash("some invoice text")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_same_text_produces_same_hash():
    assert compute_hash("invoice text") == compute_hash("invoice text")


def test_different_text_produces_different_hash():
    assert compute_hash("invoice A") != compute_hash("invoice B")


def test_whitespace_normalisation_produces_same_hash():
    assert compute_hash("invoice  text") == compute_hash("invoice text")


def test_first_submission_is_not_duplicate():
    store = DeduplicationStore()
    assert store.check_and_add("abc123") is False


def test_second_submission_of_same_hash_is_duplicate():
    store = DeduplicationStore()
    store.check_and_add("abc123")
    assert store.check_and_add("abc123") is True


def test_different_hashes_are_not_duplicates():
    store = DeduplicationStore()
    store.check_and_add("hash-a")
    assert store.check_and_add("hash-b") is False


def test_clear_resets_store():
    store = DeduplicationStore()
    store.check_and_add("abc123")
    store.clear()
    assert store.check_and_add("abc123") is False


def test_len_reflects_unique_entries():
    store = DeduplicationStore()
    store.check_and_add("a")
    store.check_and_add("b")
    store.check_and_add("a")  # duplicate
    assert len(store) == 2
