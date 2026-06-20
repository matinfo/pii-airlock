"""Shared logic for the Claude Code hooks.

Both hooks read the event JSON from stdin, run PII detection over the relevant
text, and print a decision JSON to stdout. They never rewrite the payload (the
hook API can't reliably do that) — they surface PII so the user can decide.
"""

from __future__ import annotations

import json
import sys
from collections import Counter

from pii_scrub.config import load_config
from pii_scrub.engine import ScrubEngine

# Tool-input fields worth scanning, per tool name.
_TOOL_FIELDS: dict[str, tuple[str, ...]] = {
    "Bash": ("command",),
    "Write": ("content", "file_path"),
    "Edit": ("new_string", "old_string"),
    "MultiEdit": ("edits",),
    "Read": ("file_path",),
}


def _read_event() -> dict:
    try:
        return json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return {}


def _collect_strings(value) -> list[str]:
    """Flatten nested tool-input values into a list of strings."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _collect_strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _collect_strings(v)]
    return []


def _detect_types(engine: ScrubEngine, texts: list[str]) -> Counter:
    found: Counter = Counter()
    for text in texts:
        if not text or not text.strip():
            continue
        for det in engine.detect(text):
            found[det.entity_type] += 1
    return found


def _emit(payload: dict) -> None:
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")


def run_pre_tool_use() -> None:
    event = _read_event()
    config = load_config()
    tool = event.get("tool_name", "")
    tool_input = event.get("tool_input", {}) or {}

    fields = _TOOL_FIELDS.get(tool)
    if fields is None:
        return  # tool not relevant; no decision -> allow

    texts: list[str] = []
    for field in fields:
        texts.extend(_collect_strings(tool_input.get(field)))

    found = _detect_types(ScrubEngine(config), texts)
    if not found:
        return

    summary = ", ".join(f"{t}×{n}" for t, n in found.most_common())
    decision = "deny" if config.hook_decision == "deny" else "ask"
    _emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": decision,
                "permissionDecisionReason": (
                    f"pii-scrub: PII detected in {tool} input — {summary}. "
                    "Review before this leaves your machine."
                ),
            }
        }
    )


def run_user_prompt_submit() -> None:
    event = _read_event()
    config = load_config()
    prompt = event.get("prompt", "") or ""

    found = _detect_types(ScrubEngine(config), [prompt])
    if not found:
        return

    summary = ", ".join(f"{t}×{n}" for t, n in found.most_common())
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": (
                f"⚠ pii-scrub: your prompt appears to contain PII — {summary}. "
                "Consider scrubbing it (`pii-scrub scrub`) before sending."
            ),
        }
    }
    if config.hook_decision == "deny":
        # Block the prompt entirely.
        payload["decision"] = "block"
        payload["reason"] = f"pii-scrub blocked prompt: PII detected — {summary}."
    _emit(payload)
