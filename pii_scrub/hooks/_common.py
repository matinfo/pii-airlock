"""Shared logic for the Claude Code hooks.

Both hooks read the event JSON from stdin, run PII detection over the relevant
text, and print a decision JSON to stdout. They never rewrite the payload (the
hook API can't reliably do that) — they surface PII so the user can decide.

Detection runs in the hook daemon when one answers (models stay loaded between
calls), else in this process (see ``hook_daemon`` / ``hook_fallback``).

Fail closed: if detection itself fails (missing spaCy model, unreadable file),
the input is treated as containing PII unless ``hook_on_error: open``.
"""

from __future__ import annotations

import contextlib
import json
import sys
from collections import Counter
from pathlib import Path

from pii_scrub import daemon
from pii_scrub.config import Config, load_config
from pii_scrub.engine import Detection, ScrubEngine, apply_detections
from pii_scrub.mapping import Mapping
from pii_scrub.token_key import token_key

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
        return _normalize(json.loads(sys.stdin.read() or "{}"))
    except json.JSONDecodeError:
        return {}


def _normalize(event: dict) -> dict:
    """Bring a GitHub Copilot hook payload (camelCase, `toolArgs` as a JSON string)
    to the Claude Code shape; `copilot` marks it so the reply uses Copilot's format."""
    if not isinstance(event, dict) or not ({"toolName", "sessionId"} & event.keys()):
        return event if isinstance(event, dict) else {}
    args = event.get("toolArgs")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {"raw": args}  # unparseable: still scanned as text
    return {**event, "copilot": True, "tool_name": event.get("toolName") or "",
            "tool_input": args if isinstance(args, dict) else {}}


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


def _analyze(config: Config, event: dict, texts: list[str]) -> list[tuple[str, list[Detection]]]:
    """(chunk, detections) for every chunk of `texts`, via the daemon if it answers."""
    chunks = [c for text in texts if text and text.strip() for c in _chunks(text)]
    if not chunks:
        return []
    cwd = event.get("cwd") or None
    if config.hook_daemon != "off":
        found = daemon.detect(cwd, chunks)  # DaemonError: detection failed, fail closed
        if found is not None:
            return [(chunk, [Detection(*d) for d in dets])
                    for chunk, dets in zip(chunks, found, strict=True)]
        if config.hook_daemon == "auto":
            with contextlib.suppress(OSError):
                daemon.spawn(cwd)  # ready for the next call; this one runs here
    engine = ScrubEngine(config, regex_only=config.hook_fallback == "regex")
    engine.prime(chunks)
    return [(chunk, engine.detect(chunk)) for chunk in chunks]


def _types(results: list[tuple[str, list[Detection]]]) -> Counter:
    return Counter(d.entity_type for _, dets in results for d in dets)


# Shown with every detection so a false positive costs one command to fix.
_FALSE_POSITIVE_HINT = (
    'False positive? `pii-airlock allow "<term>"` adds it to this project\'s policy.'
)


def _summary(found: Counter) -> str:
    return ", ".join(f"{t}×{n}" for t, n in found.most_common())


def _blocked(config: Config, found: Counter) -> Counter:
    """Entities whose `entity_actions` policy is `block`: never sent, never asked."""
    return Counter({t: n for t, n in found.items() if config.action_for(t) == "block"})


def _emit(payload: dict) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


def _tool_texts(tool: str, tool_input: dict, event: dict, config: Config) -> list[str] | None:
    """Strings to scan for this tool call, or None if the tool is not covered."""
    if tool.startswith("mcp__") or event.get("copilot"):
        # MCP tools, and every Copilot tool (its tool and argument names are not
        # Claude Code's, so scan every argument rather than guess which ones matter).
        texts = _collect_strings(tool_input)
        if event.get("copilot") and tool.lower() in ("view", "read"):
            path = tool_input.get("path") or tool_input.get("file_path")
            content = _read_file_text({"file_path": path}, event.get("cwd"), config)
            if content:
                texts.append(content)
        return texts
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
            found = _types(_analyze(config, event, texts))
    except _FAILURES as exc:
        if config.hook_on_error == "open":
            return
        reason = f"pii-airlock could not check {tool} input for PII: {_error_text(exc)}"
    else:
        if not found:
            return
        reason = (
            f"pii-airlock: PII detected in {tool} input — {_summary(found)}. "
            f"Review before this leaves your machine. {_FALSE_POSITIVE_HINT}"
        )
        blocked = _blocked(config, found)
        if blocked:
            decision = "deny"
            reason = (f"pii-airlock: {tool} input blocked by policy (entity_actions) — "
                      f"{_summary(blocked)}. Use a placeholder instead.")
    if event.get("copilot"):
        _emit({"permissionDecision": decision, "permissionDecisionReason": reason})
        return
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
            results = _analyze(config, event, [prompt])
            found = _types(results)
            blocked = _blocked(config, found)
            scrubbed = None
            if len(results) == 1:  # long pastes are chunked: count only
                # Same tokens as the gateway would send, so the two can be mixed;
                # redacted and blocked entities become [ENTITY].
                hidden = {e for e, a in config.entity_actions.items() if a == "redact"}
                scrubbed = apply_detections(prompt, results[0][1], Mapping(token_key(config)),
                                            hidden | set(blocked))
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
    if block or blocked:
        reason = f"pii-airlock blocked your prompt: PII detected — {summary}."
        if blocked:
            reason = (f"pii-airlock blocked your prompt: {_summary(blocked)} is blocked by "
                      f"policy (entity_actions); also found: {summary}.")
        if scrubbed is not None:
            reason += f"\n\nScrubbed version you can send instead:\n\n{scrubbed}"
        reason += f"\n\n{_FALSE_POSITIVE_HINT}"
        if not blocked:
            reason += " Set `prompt_decision: warn` to send prompts with a warning instead."
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
