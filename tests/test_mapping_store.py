from __future__ import annotations

import pytest

from pii_scrub.mapping_store import (
    FileMappingStore,
    InMemoryMappingStore,
    build_mapping_store,
)


def test_in_memory_store_roundtrip():
    store = InMemoryMappingStore()
    mapping = store.create()
    token = mapping.token_for("PERSON", "Alice")
    key = store.save(mapping)

    loaded = store.load(key)
    assert loaded.restore(f"call {token}") == "call Alice"

    store.delete(key)
    with pytest.raises(KeyError):
        store.load(key)


def test_file_store_roundtrip(tmp_path):
    store = FileMappingStore(tmp_path)
    mapping = store.create()
    mapping.token_for("EMAIL_ADDRESS", "alice@example.com")
    key = store.save(mapping, key="req-1")

    loaded = store.load(key)
    assert loaded.restore("<EMAIL_ADDRESS_1>") == "alice@example.com"

    store.delete(key)
    with pytest.raises(FileNotFoundError):
        store.load(key)


def test_file_store_rejects_unsafe_key(tmp_path):
    store = FileMappingStore(tmp_path)
    mapping = store.create()
    with pytest.raises(ValueError):
        store.save(mapping, key="../escape")


def test_build_mapping_store():
    assert isinstance(build_mapping_store("memory"), InMemoryMappingStore)
    assert isinstance(build_mapping_store("file"), FileMappingStore)
    with pytest.raises(ValueError):
        build_mapping_store("bogus")
