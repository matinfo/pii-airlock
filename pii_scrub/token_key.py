"""Secret key behind stable tokens (``token_style: stable``).

A stable token is a keyed hash of the value (``<PERSON_482913>``): the same
value gets the same token in every request, file and process. Sequential
tokens (``<PERSON_1>``) are numbered in reading order, so they change as soon
as the order does — a trimmed or compacted history, a subagent, a parallel
request — and the model then sees one person under two names, and prompt
caches miss.

Without the key a token reveals nothing about its value (no dictionary attack
on names). The key used is derived per period (``token_rotation``): tokens are
stable within a day or week, and unlinkable across periods, so the provider
cannot follow one person across all your conversations.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import date
from functools import cache
from pathlib import Path

from .mapping import Mapping
from .mapping_store import default_state_dir

ROTATIONS = ("day", "week", "never")


def key_path() -> Path:
    return default_state_dir() / "token.key"


@cache
def _master_key(path: Path) -> bytes:
    """The user's 32-byte master key, created on first use (owner-only)."""
    try:
        key = path.read_bytes()
        if len(key) == 32:
            return key
        raise ValueError(f"{path} is corrupt (expected 32 bytes); delete it to rotate")
    except FileNotFoundError:
        pass
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Write a private temp file, then link it into place: concurrent first
    # uses (proxy, hooks, daemon) all end up with the one key that won.
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(secrets.token_bytes(32))
        try:
            os.link(tmp, path)
        except FileExistsError:
            pass
        except OSError:  # no hard links (e.g. FAT): last writer wins, once
            if not path.exists():
                os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return _master_key(path)


def period(rotation: str, today: date | None = None) -> str:
    today = today or date.today()
    if rotation == "day":
        return today.isoformat()
    if rotation == "week":
        year, week, _ = today.isocalendar()
        return f"{year}-W{week:02d}"
    if rotation == "never":
        return "never"
    raise ValueError(f"token_rotation must be one of {', '.join(ROTATIONS)}, not {rotation!r}")


def token_key(config, today: date | None = None) -> bytes | None:
    """Key for this period's stable tokens, or None for sequential tokens."""
    if config.token_style == "sequential":
        return None
    if config.token_style not in ("stable", "surrogate"):
        raise ValueError(
            f"token_style must be stable, surrogate or sequential, not {config.token_style!r}"
        )
    label = period(config.token_rotation, today).encode()
    return hmac.new(_master_key(key_path()), b"pii-airlock tokens " + label,
                    hashlib.sha256).digest()


def new_mapping(config) -> Mapping:
    """An empty mapping minting tokens (or fakes) the way `config` asks."""
    return Mapping(token_key(config), surrogates=config.token_style == "surrogate")
