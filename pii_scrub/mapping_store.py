"""Pluggable mapping storage backends.

This is a small abstraction layer so runtime components (like the proxy) can
swap mapping persistence strategies without changing scrub/restore logic.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from .mapping import Mapping

_SAFE_KEY_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class MappingStore(Protocol):
    """Interface for creating/loading/saving mapping objects."""

    def create(self, key: bytes | None = None, *, surrogates: bool = False) -> Mapping:
        """A new mapping; `key` makes its tokens stable (see token_key.py)."""
        ...

    def save(self, mapping: Mapping, *, key: str | None = None) -> str: ...

    def load(self, key: str) -> Mapping: ...

    def delete(self, key: str) -> None: ...


class InMemoryMappingStore:
    """Process-local mapping storage (default, fastest, ephemeral)."""

    def __init__(self) -> None:
        self._items: dict[str, Mapping] = {}

    def create(self, key: bytes | None = None, *, surrogates: bool = False) -> Mapping:
        return Mapping(key, surrogates=surrogates)

    def save(self, mapping: Mapping, *, key: str | None = None) -> str:
        token = key or uuid4().hex
        self._items[token] = mapping
        return token

    def load(self, key: str) -> Mapping:
        try:
            return self._items[key]
        except KeyError as exc:
            raise KeyError(f"Mapping key not found: {key}") from exc

    def delete(self, key: str) -> None:
        self._items.pop(key, None)


class FileMappingStore:
    """Filesystem-backed mapping storage rooted under one directory.

    With `encrypt_key`, files are written encrypted (see mapping_crypto.py); files
    written without it still load.
    """

    def __init__(self, root: str | Path, encrypt_key: bytes | None = None) -> None:
        self._encrypt_key = encrypt_key
        self._root = Path(root)
        # Mapping files hold real PII: owner-only directory.
        self._root.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            os.chmod(self._root, 0o700)
        except OSError:
            pass  # best effort (e.g. filesystems without POSIX perms)

    def create(self, key: bytes | None = None, *, surrogates: bool = False) -> Mapping:
        return Mapping(key, surrogates=surrogates)

    def save(self, mapping: Mapping, *, key: str | None = None) -> str:
        token = key or uuid4().hex
        path = self._path_for(token)
        mapping.save(path, encrypt_key=self._encrypt_key)
        return token

    def load(self, key: str) -> Mapping:
        return Mapping.load(self._path_for(key), encrypt_key=self._encrypt_key)

    def delete(self, key: str) -> None:
        self._path_for(key).unlink(missing_ok=True)

    def _path_for(self, key: str) -> Path:
        if not _SAFE_KEY_RE.fullmatch(key):
            raise ValueError("Invalid mapping key (allowed: letters, digits, ., _, -)")
        return self._root / f"{key}.pii-map.json"


def default_state_dir() -> Path:
    """``$XDG_STATE_HOME/pii-airlock`` (``~/.local/state/pii-airlock`` by default)."""
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "pii-airlock"


def build_mapping_store(
    backend: str = "memory", *, root: str | Path | None = None, encrypt: bool = True
) -> MappingStore:
    """Factory for mapping stores.

    Supported backends:
      - memory (default): process-local, ephemeral
      - file: JSON files under `root` (default: the user state dir, never the
        project directory, where real PII could be committed or synced),
        encrypted with a key derived from token.key unless `encrypt` is false
    """
    if backend == "memory":
        return InMemoryMappingStore()
    if backend == "file":
        from .mapping_crypto import default_key

        return FileMappingStore(
            Path(root) if root is not None else default_state_dir() / "maps",
            encrypt_key=default_key() if encrypt else None,
        )
    raise ValueError(f"Unknown mapping backend '{backend}'. Supported: memory, file.")
