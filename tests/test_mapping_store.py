from __future__ import annotations

import os

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


def test_file_store_defaults_to_private_state_dir(tmp_path, monkeypatch):
    import stat

    from pii_scrub.mapping_store import build_mapping_store

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.chdir(tmp_path)
    store = build_mapping_store("file")
    key = store.save(store.create())
    root = tmp_path / "state" / "pii-airlock" / "maps"
    assert (root / f"{key}.pii-map.json").is_file()
    if os.name == "posix":  # Windows does not report POSIX modes
        assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert not (tmp_path / ".pii-airlock-maps").exists()  # nothing in the project dir
