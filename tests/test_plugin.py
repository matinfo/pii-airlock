"""The Claude Code plugin (plugins/pii-airlock) stays in step with the CLI."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from pii_scrub import __version__
from pii_scrub.hookinstall import HOOK_SPECS

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "pii-airlock"
LAUNCH = PLUGIN / "hooks" / "launch.sh"
posix = pytest.mark.skipif(sys.platform == "win32", reason="the launcher is a POSIX script")


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_plugin_version_matches_the_package():
    assert _json(PLUGIN / ".claude-plugin" / "plugin.json")["version"] == __version__
    assert re.search(rf'^version = "{re.escape(__version__)}"$',
                     (ROOT / "pyproject.toml").read_text(), re.M)


def test_marketplace_lists_the_plugin():
    market = _json(ROOT / ".claude-plugin" / "marketplace.json")
    (entry,) = market["plugins"]
    assert entry["name"] == _json(PLUGIN / ".claude-plugin" / "plugin.json")["name"]
    assert (ROOT / entry["source"]).resolve() == PLUGIN.resolve()


def test_plugin_hooks_match_what_install_hook_registers():
    hooks = _json(PLUGIN / "hooks" / "hooks.json")["hooks"]
    for event, (command, matcher) in HOOK_SPECS.items():
        (group,) = hooks[event]
        assert group.get("matcher") == matcher
        wanted = command.rsplit(" ", 1)[1]  # "pre-tool-use"
        assert [h["command"] for h in group["hooks"]] == [
            f'"${{CLAUDE_PLUGIN_ROOT}}"/hooks/launch.sh {wanted}']


def _run(event, tmp_path, *, with_cli, env_extra=None, stdin=""):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    if with_cli:
        fake = bindir / "pii-airlock"
        fake.write_text('#!/bin/sh\necho "args:$*"\ncat\n')
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    # Only the system dirs plus ours: a real pii-airlock on the dev machine must not leak in.
    env = {"PATH": f"{bindir}:/usr/bin:/bin", **(env_extra or {})}
    return subprocess.run([str(LAUNCH), event], input=stdin, capture_output=True, text=True,
                          env=env, check=False)


@posix
def test_launcher_is_executable():
    assert os.access(LAUNCH, os.X_OK)


@posix
@pytest.mark.parametrize("event", ["pre-tool-use", "user-prompt-submit"])
def test_launcher_blocks_when_the_cli_is_missing(tmp_path, event):
    result = _run(event, tmp_path, with_cli=False)
    assert result.returncode == 2 and "not installed" in result.stderr


@posix
def test_launcher_can_fail_open_on_request(tmp_path):
    result = _run("pre-tool-use", tmp_path, with_cli=False,
                  env_extra={"PII_AIRLOCK_PLUGIN_FAIL_OPEN": "1"})
    assert result.returncode == 0


@posix
def test_session_start_explains_a_missing_cli_without_blocking(tmp_path):
    result = _run("session-start", tmp_path, with_cli=False)
    assert result.returncode == 0 and "brew install" in result.stdout


@posix
def test_launcher_forwards_event_and_stdin_to_the_cli(tmp_path):
    result = _run("pre-tool-use", tmp_path, with_cli=True, stdin='{"tool":"Bash"}')
    assert result.returncode == 0
    assert "args:hook pre-tool-use" in result.stdout and '{"tool":"Bash"}' in result.stdout


@posix
def test_session_start_is_silent_when_the_cli_is_present(tmp_path):
    result = _run("session-start", tmp_path, with_cli=True)
    assert result.returncode == 0 and result.stdout == ""
