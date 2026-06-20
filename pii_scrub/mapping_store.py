"""Pluggable mapping storage backends.

This is a small abstraction layer so runtime components (like the proxy) can
swap mapping persistence strategies without changing scrub/restore logic.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from .mapping import Mapping

_SAFE_KEY_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class MappingStore(Protocol):
    """Interface for creating/loading/saving mapping objects."""

    def create(self) -> Mapping: ...

    def save(self, mapping: Mapping, *, key: str | None = None) -> str: ...

    def load(self, key: str) -> Mapping: ...

    def delete(self, key: str) -> None: ...


class InMemoryMappingStore:
    """Process-local mapping storage (default, fastest, ephemeral)."""

    def __init__(self) -> None:
        self._items: dict[str, Mapping] = {}

    def create(self) -> Mapping:
        return Mapping()

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
    """Filesystem-backed mapping storage rooted under one directory."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def create(self) -> Mapping:
        return Mapping()

    def save(self, mapping: Mapping, *, key: str | None = None) -> str:
        token = key or uuid4().hex
        path = self._path_for(token)
        mapping.save(path)
        return token

    def load(self, key: str) -> Mapping:
        return Mapping.load(self._path_for(key))

    def delete(self, key: str) -> None:
        self._path_for(key).unlink(missing_ok=True)

    def _path_for(self, key: str) -> Path:
        if not _SAFE_KEY_RE.fullmatch(key):
            raise ValueError("Invalid mapping key (allowed: letters, digits, ., _, -)")
        return self._root / f"{key}.pii-map.json"


def build_mapping_store(
    backend: str = "memory", *, root: str | Path | None = None
) -> MappingStore:
    """Factory for mapping stores.

    Supported backends:
      - memory (default): process-local, ephemeral
      - file: JSON files under `root` (or `./.pii-airlock-maps`)
    """
    if backend == "memory":
        return InMemoryMappingStore()
    if backend == "file":
        base = Path(root) if root is not None else (Path.cwd() / ".pii-airlock-maps")
        return FileMappingStore(base)
    raise ValueError(f"Unknown mapping backend '{backend}'. Supported: memory, file.")
