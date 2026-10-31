"""Which projects may loosen protection (direnv-style trust).

A project's ``.pii-airlock.yaml`` and ``SKILL.md`` policy come with the repo: a
cloned, untrusted repo could ship ``hook_on_error: open`` or
``entity_actions: {PERSON: allow}`` and switch your protections off. So project
config is *tightened only* until you trust it: it may add deny-list terms and
patterns, and raise actions/decisions to ``block`` / ``redact`` / ``deny``, but
nothing that lets more through.

Trust is a fingerprint of the project's policy files, stored in the state dir.
Editing them with ``pii-airlock allow|deny|action|policy init`` re-trusts them
(you just ran it); a ``git pull`` that changes them does not, until you run
``pii-airlock trust``. User-level config is always trusted.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from .mapping_store import default_state_dir

PROJECT_FILES = (Path(".pii-airlock.yaml"), Path(".claude") / "skills" / "pii-airlock" / "SKILL.md")


def _store() -> Path:
    return default_state_dir() / "trust.json"


def fingerprint(project: str | Path) -> str:
    root = Path(project)
    digest = hashlib.sha256()
    for rel in PROJECT_FILES:
        path = root / rel
        digest.update(str(rel).encode() + b"\0")
        digest.update(path.read_bytes() if path.is_file() else b"-")
    return digest.hexdigest()


def _key(project: str | Path) -> str:
    return str(Path(project).resolve())


def _load() -> dict[str, str]:
    try:
        data = json.loads(_store().read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def has_project_config(project: str | Path) -> bool:
    return any((Path(project) / rel).is_file() for rel in PROJECT_FILES)


def is_trusted(project: str | Path) -> bool:
    """Trusted: nothing to distrust, or the files match what you trusted."""
    return not has_project_config(project) or _load().get(_key(project)) == fingerprint(project)


def trust(project: str | Path) -> None:
    store = _store()
    store.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    data = _load()
    data[_key(project)] = fingerprint(project)
    tmp = store.with_name(f".trust.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, store)


_TIGHTER = {
    "hook_decision": {"deny"},
    "prompt_decision": {"block"},
    "hook_on_error": {"closed"},
}


def tighten_only(data: dict) -> tuple[dict, list[str]]:
    """The part of untrusted project config that cannot let more through.

    Returns (safe_data, names_of_ignored_keys).
    """
    safe: dict = {}
    ignored: list[str] = []
    for key, value in data.items():
        if key in ("deny_list", "custom_patterns"):
            safe[key] = value
        elif key in _TIGHTER:
            if str(value).lower() in _TIGHTER[key]:
                safe[key] = value
            else:
                ignored.append(key)
        elif key == "entity_actions" and isinstance(value, dict):
            keep = {e: a for e, a in value.items() if str(a).strip().lower() in ("block", "redact")}
            if keep:
                safe[key] = keep
            ignored += [f"entity_actions.{e}" for e in value if e not in keep]
        else:
            ignored.append(key)
    return safe, ignored
