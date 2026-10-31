"""GitHub Copilot hook support: payload normalization, reply format, installer."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest

import pii_scrub.hookinstall as hookinstall
from pii_scrub.hooks import _common


def _run(monkeypatch, capsys, event, found=("EMAIL_ADDRESS",)):
    seen: list[str] = []

    def analyze(_config, _event, texts):
        seen.extend(texts)
        return [SimpleNamespace(entity_type=t) for t in found]

    monkeypatch.setattr(_common, "_analyze", analyze)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(event)))
    _common.run_pre_tool_use()
    out = capsys.readouterr().out
    return (json.loads(out) if out.strip() else None), seen


def test_copilot_payload_is_scanned_and_answered_in_copilot_format(monkeypatch, capsys):
    event = {"sessionId": "s", "cwd": "/tmp", "toolName": "bash",
             "toolArgs": json.dumps({"command": "mail jean@acme.fr"})}
    reply, seen = _run(monkeypatch, capsys, event)
    assert seen == ["mail jean@acme.fr"]
    assert reply["permissionDecision"] in ("ask", "deny")
    assert "pii-airlock" in reply["permissionDecisionReason"]
    assert "hookSpecificOutput" not in reply


def test_copilot_tools_with_unknown_names_are_still_scanned(monkeypatch, capsys):
    event = {"toolName": "some_new_tool", "toolArgs": json.dumps({"a": {"b": ["x@y.io"]}})}
    _, seen = _run(monkeypatch, capsys, event)
    assert seen == ["x@y.io"]


def test_copilot_unparseable_args_are_scanned_as_text(monkeypatch, capsys):
    event = {"toolName": "bash", "toolArgs": "not json jean@acme.fr"}
    reply, seen = _run(monkeypatch, capsys, event)
    assert seen == ["not json jean@acme.fr"] and reply is not None


def test_copilot_clean_call_is_allowed_silently(monkeypatch, capsys):
    reply, _ = _run(monkeypatch, capsys, {"toolName": "bash", "toolArgs": "{}"}, found=())
    assert reply is None


def test_copilot_view_scans_the_file_content(monkeypatch, capsys, tmp_path):
    f = tmp_path / "notes.txt"
    f.write_text("contact jean@acme.fr")
    event = {"toolName": "view", "cwd": str(tmp_path),
             "toolArgs": json.dumps({"path": "notes.txt"})}
    _, seen = _run(monkeypatch, capsys, event)
    assert "contact jean@acme.fr" in seen


def test_claude_payload_keeps_the_claude_reply(monkeypatch, capsys):
    event = {"tool_name": "Bash", "tool_input": {"command": "mail jean@acme.fr"}}
    reply, _ = _run(monkeypatch, capsys, event)
    assert reply["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert "permissionDecision" not in reply


def test_install_copilot_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path, changed = hookinstall.install_copilot("project")
    assert changed and path == tmp_path / ".github" / "hooks" / "pii-airlock.json"
    data = json.loads(path.read_text())
    assert data["version"] == 1
    assert data["hooks"]["preToolUse"][0]["bash"] == "pii-airlock hook pre-tool-use"
    assert hookinstall.install_copilot("project") == (path, False)


def test_install_copilot_user_scope_honours_copilot_home(tmp_path, monkeypatch):
    monkeypatch.setenv("COPILOT_HOME", str(tmp_path / "cp"))
    path, _ = hookinstall.install_copilot("user")
    assert path == tmp_path / "cp" / "hooks" / "pii-airlock.json" and path.is_file()


@pytest.mark.parametrize("scope", ["project", "user"])
def test_cli_target_copilot(tmp_path, monkeypatch, scope):
    from typer.testing import CliRunner

    import pii_scrub.cli as cli

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COPILOT_HOME", str(tmp_path / "cp"))
    result = CliRunner().invoke(cli.app, ["install-hook", "--target", "copilot", "--scope", scope])
    assert result.exit_code == 0 and "preToolUse" in result.output
