"""Register / inspect pii-airlock hooks in a Claude Code settings.json.

Kept free of heavy imports so it stays fast and unit-testable.
"""

from __future__ import annotations

import json
from pathlib import Path

PROJECT_SETTINGS = Path.cwd() / ".claude" / "settings.json"
USER_SETTINGS = Path.home() / ".claude" / "settings.json"

# event name -> (console command, optional tool matcher)
HOOK_SPECS: dict[str, tuple[str, str | None]] = {
    "PreToolUse": ("pii-airlock hook pre-tool-use", "Bash|Write|Edit|MultiEdit|Read"),
    "UserPromptSubmit": ("pii-airlock hook user-prompt-submit", None),
}

# CLI --event value -> list of settings event names
EVENT_CHOICES: dict[str, list[str]] = {
    "both": ["PreToolUse", "UserPromptSubmit"],
    "tool": ["PreToolUse"],
    "prompt": ["UserPromptSubmit"],
}


def settings_path(scope: str) -> Path:
    return USER_SETTINGS if scope == "user" else PROJECT_SETTINGS


def _load(path: Path) -> dict:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8") or "{}")
    return {}


def install(event: str, scope: str) -> tuple[Path, list[str]]:
    """Add the requested hooks to settings.json. Idempotent.

    Returns (settings_path, list_of_events_added).
    """
    if event not in EVENT_CHOICES:
        raise ValueError(f"--event must be one of {', '.join(EVENT_CHOICES)}")
    path = settings_path(scope)
    settings = _load(path)
    hooks = settings.setdefault("hooks", {})

    added: list[str] = []
    for ev in EVENT_CHOICES[event]:
        command, matcher = HOOK_SPECS[ev]
        groups = hooks.setdefault(ev, [])
        if _already_present(groups, command):
            continue
        entry: dict = {"hooks": [{"type": "command", "command": command}]}
        if matcher:
            entry["matcher"] = matcher
        groups.append(entry)
        added.append(ev)

    if added:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    return path, added


def _already_present(groups: list, command: str) -> bool:
    for group in groups:
        for hook in group.get("hooks", []):
            if hook.get("command") == command:
                return True
    return False
