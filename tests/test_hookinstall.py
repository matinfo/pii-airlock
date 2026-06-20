"""install-hook settings.json manipulation (no Presidio needed)."""

import json

import pii_scrub.hookinstall as hi


def _patch_paths(monkeypatch, tmp_path):
    proj = tmp_path / ".claude" / "settings.json"
    monkeypatch.setattr(hi, "PROJECT_SETTINGS", proj)
    monkeypatch.setattr(hi, "USER_SETTINGS", tmp_path / "user.json")
    return proj


def test_install_both_creates_two_events(monkeypatch, tmp_path):
    proj = _patch_paths(monkeypatch, tmp_path)
    path, added = hi.install("both", "project")
    assert path == proj
    assert set(added) == {"PreToolUse", "UserPromptSubmit"}

    data = json.loads(proj.read_text())
    assert "PreToolUse" in data["hooks"]
    assert "UserPromptSubmit" in data["hooks"]
    cmd = data["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert cmd == "pii-scrub hook pre-tool-use"
    assert data["hooks"]["PreToolUse"][0]["matcher"]  # tool matcher present


def test_install_is_idempotent(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    hi.install("both", "project")
    _, added_again = hi.install("both", "project")
    assert added_again == []


def test_install_preserves_existing_settings(monkeypatch, tmp_path):
    proj = _patch_paths(monkeypatch, tmp_path)
    proj.parent.mkdir(parents=True)
    proj.write_text(json.dumps({"model": "opus", "hooks": {}}))
    hi.install("prompt", "project")
    data = json.loads(proj.read_text())
    assert data["model"] == "opus"
    assert "UserPromptSubmit" in data["hooks"]
    assert "PreToolUse" not in data["hooks"]


def test_invalid_event(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    try:
        hi.install("nope", "project")
    except ValueError:
        return
    raise AssertionError("expected ValueError")
