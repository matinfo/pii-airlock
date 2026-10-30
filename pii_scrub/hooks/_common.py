"""Shared logic for the Claude Code hooks.

Both hooks read the event JSON from stdin, run PII detection over the relevant
text, and print a decision JSON to stdout. They never rewrite the payload (the
hook API can't reliably do that) — they surface PII so the user can decide.

Fail closed: if detection itself fails (missing spaCy model, unreadable file),
the input is treated as containing PII unless ``hook_on_error: open``.
"""

from __future__ import annotations

import contextlib
import json
import sys
from collections import Counter
from pathlib import Path

from pii_scrub.config import Config, load_config
from pii_scrub.engine import ScrubEngine, apply_detections
from pii_scrub.mapping import Mapping

# Tool-input fields worth scanning, per tool name. `Read` is special-cased: the
# file *content* is what reaches the model, so the hook reads and scans it.
_TOOL_FIELDS: dict[str, tuple[str, ...]] = {
    "Bash": ("command",),
    "Write": ("content", "file_path"),
    "Edit": ("new_string", "old_string"),
    "MultiEdit": ("edits",),
    "NotebookEdit": ("new_source",),
    "Read": ("file_path",),
    "Grep": ("pattern", "path", "glob"),
    "WebFetch": ("url", "prompt"),
    "WebSearch": ("query",),
}

# Chunk size for scanning file contents (spaCy refuses texts over ~1M chars).
_CHUNK_CHARS = 100_000


class _ScanError(Exception):
    """Detection could not run; handled according to `hook_on_error`."""


# Failures that must not end the hook before it prints a decision: a non-zero
# exit makes Claude Code treat the hook as a non-blocking error (fail open).
# SystemExit included: spaCy's model downloader calls sys.exit().
_FAILURES = (Exception, SystemExit)


def _error_text(exc: BaseException) -> str:
    detail = str(exc) or type(exc).__name__
    if isinstance(exc, SystemExit):
        detail = "a library exited during detection (missing spaCy model?)"
    return (f"{detail} Run `pii-airlock doctor`, or set `hook_on_error: open` "
            "to skip checks.")


def _quiet():
    """Keep library chatter off stdout, which Claude Code parses as JSON."""
    return contextlib.redirect_stdout(sys.stderr)


def _read_event() -> dict:
    try:
        return json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return {}


def _load_config(event: dict) -> tuple[Config, BaseException | None]:
    """Config for the project Claude Code reports (its SKILL.md policy applies).

    A broken config (e.g. invalid YAML in the policy block) must not crash the
    hook — that would fail open. Fall back to defaults and report the error.
    """
    try:
        return load_config(cwd=event.get("cwd") or None), None
    except _FAILURES as exc:
        return Config(), exc


def _collect_strings(value) -> list[str]:
    """Flatten nested tool-input values into a list of strings."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _collect_strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _collect_strings(v)]
    return []


def _chunks(text: str) -> list[str]:
    """Split long text on line boundaries into pieces spaCy can handle."""
    if len(text) <= _CHUNK_CHARS:
        return [text]
    out: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        if current and len(current) + len(line) > _CHUNK_CHARS:
            out.append(current)
            current = ""
        current += line
    if current:
        out.append(current)
    return out


def _read_file_text(tool_input: dict, cwd: str | None, config: Config) -> str | None:
    """Text Claude's Read tool will see, or None if there is nothing to scan."""
    raw_path = tool_input.get("file_path")
    if not isinstance(raw_path, str) or not raw_path:
        return None
    path = Path(raw_path).expanduser()
    if not path.is_absolute() and cwd:
        path = Path(cwd) / path
    if not path.is_file():
        return None  # Read will fail on its own; nothing leaves the machine
    try:
        size = path.stat().st_size
        if size > config.hook_max_file_bytes:
            raise _ScanError(
                f"{path.name} is {size} bytes, over hook_max_file_bytes "
                f"({config.hook_max_file_bytes})"
            )
        data = path.read_bytes()
    except OSError as exc:
        raise _ScanError(f"cannot read {path.name}: {exc}") from exc
    if b"\x00" in data[:8192]:
        return None  # binary (image, PDF, ...) — not scanned as text
    text = data.decode("utf-8", errors="replace")
    offset, limit = tool_input.get("offset"), tool_input.get("limit")
    if isinstance(offset, int) or isinstance(limit, int):
        lines = text.splitlines(keepends=True)
        start = max((offset or 1) - 1, 0)
        end = start + limit if isinstance(limit, int) else None
        text = "".join(lines[start:end])
    return text


def _detect_types(engine: ScrubEngine, texts: list[str]) -> Counter:
    found: Counter = Counter()
    for text in texts:
        if not text or not text.strip():
            continue
        for chunk in _chunks(text):
            for det in engine.detect(chunk):
                found[det.entity_type] += 1
    return found


def _summary(found: Counter) -> str:
    return ", ".join(f"{t}×{n}" for t, n in found.most_common())


def _emit(payload: dict) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


def _tool_texts(tool: str, tool_input: dict, event: dict, config: Config) -> list[str] | None:
    """Strings to scan for this tool call, or None if the tool is not covered."""
    if tool.startswith("mcp__"):
        return _collect_strings(tool_input)  # MCP tools: every argument
    fields = _TOOL_FIELDS.get(tool)
    if fields is None:
        return None
    texts: list[str] = []
    for field in fields:
        texts.extend(_collect_strings(tool_input.get(field)))
    if tool == "Read":
        content = _read_file_text(tool_input, event.get("cwd"), config)
        if content:
            texts.append(content)
    return texts


def run_pre_tool_use() -> None:
    event = _read_event()
    config, config_error = _load_config(event)
    tool = event.get("tool_name", "") or ""
    tool_input = event.get("tool_input", {}) or {}
    decision = "deny" if config.hook_decision == "deny" else "ask"

    try:
        with _quiet():
            texts = _tool_texts(tool, tool_input, event, config)
            if texts is not None and config_error is not None:
                raise config_error
            if texts is None:
                return  # tool not relevant; no decision -> allow
            found = _detect_types(ScrubEngine(config), texts)
    except _FAILURES as exc:
        if config.hook_on_error == "open":
            return
        reason = f"pii-airlock could not check {tool} input for PII: {_error_text(exc)}"
    else:
        if not found:
            return
        reason = (
            f"pii-airlock: PII detected in {tool} input — {_summary(found)}. "
            "Review before this leaves your machine."
        )
    _emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": decision,
                "permissionDecisionReason": reason,
            }
        }
    )


def run_user_prompt_submit() -> None:
    event = _read_event()
    config, config_error = _load_config(event)
    prompt = event.get("prompt", "") or ""
    block = config.prompt_decision != "warn" or config.hook_decision == "deny"

    try:
        with _quiet():
            if config_error is not None:
                raise config_error
            engine = ScrubEngine(config)
            if len(prompt) <= _CHUNK_CHARS:
                detections = engine.detect(prompt)
                found = Counter(d.entity_type for d in detections)
                scrubbed = apply_detections(prompt, detections, Mapping())
            else:  # long paste: count only (offsets would span chunks)
                found = _detect_types(engine, [prompt])
                scrubbed = None
    except _FAILURES as exc:
        if config.hook_on_error == "open":
            return
        _emit({
            "decision": "block",
            "reason": f"pii-airlock could not check your prompt for PII: {_error_text(exc)}",
        })
        return

    if not found:
        return
    summary = _summary(found)
    if block:
        reason = f"pii-airlock blocked your prompt: PII detected — {summary}."
        if scrubbed is not None:
            reason += f"\n\nScrubbed version you can send instead:\n\n{scrubbed}"
        reason += "\n\n(Set `prompt_decision: warn` to send prompts with a warning instead.)"
        _emit({"decision": "block", "reason": reason})
        return
    _emit(
        {
            "systemMessage": f"⚠ pii-airlock: your prompt contains PII — {summary}. "
                             "It was sent unchanged.",
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": (
                    f"pii-airlock: the user's prompt contains PII ({summary}). "
                    "Do not repeat it unnecessarily."
                ),
            },
        }
    )
