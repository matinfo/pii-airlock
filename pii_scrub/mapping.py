"""Reversible token <-> real-value mapping.

A Mapping mints stable placeholder tokens like ``<PERSON_1>`` for detected PII
and remembers the original value so it can be restored after an LLM round-trip.

SECURITY: the saved mapping file contains the *real* PII. It is written with
0600 permissions and should never be committed (see .gitignore). Treat it like
a secret.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

# Matches any token this module mints, e.g. <PERSON_1>, <EMAIL_ADDRESS_12>.
TOKEN_RE = re.compile(r"<([A-Z][A-Z0-9_]*)_(\d+)>")


class Mapping:
    """Bidirectional, deterministic store of value <-> token pairs."""

    def __init__(self) -> None:
        # (entity_type, value) -> token
        self._value_to_token: dict[tuple[str, str], str] = {}
        # token -> value
        self._token_to_value: dict[str, str] = {}
        # entity_type -> highest index used
        self._counters: dict[str, int] = {}

    def token_for(self, entity_type: str, value: str) -> str:
        """Return the existing token for this value, or mint the next one."""
        key = (entity_type, value)
        existing = self._value_to_token.get(key)
        if existing is not None:
            return existing
        idx = self._counters.get(entity_type, 0) + 1
        self._counters[entity_type] = idx
        token = f"<{entity_type}_{idx}>"
        self._value_to_token[key] = token
        self._token_to_value[token] = value
        return token

    def restore(self, text: str) -> str:
        """Replace every known token in `text` with its original value."""
        return TOKEN_RE.sub(
            lambda m: self._token_to_value.get(m.group(0), m.group(0)),
            text,
        )

    def __len__(self) -> int:
        return len(self._token_to_value)

    # --- persistence -----------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "version": 1,
            "tokens": self._token_to_value,
            "counters": self._counters,
        }

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass  # best effort (e.g. on filesystems without POSIX perms)

    @classmethod
    def load(cls, path: str | Path) -> Mapping:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        m = cls()
        m._token_to_value = dict(data.get("tokens", {}))
        m._counters = dict(data.get("counters", {}))
        for token, value in m._token_to_value.items():
            match = TOKEN_RE.fullmatch(token)
            if match:
                m._value_to_token[(match.group(1), value)] = token
        return m
