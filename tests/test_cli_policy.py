"""CLI tests for the policy commands (allow / deny / policy init|show)."""

from __future__ import annotations

from typer.testing import CliRunner

from pii_scrub.cli import app
from pii_scrub.config import load_config
from pii_scrub.policy import skill_path

runner = CliRunner()


def _project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")
    return skill_path("project", tmp_path)


def test_policy_init_creates_skill_once(tmp_path, monkeypatch):
    path = _project(tmp_path, monkeypatch)
    result = runner.invoke(app, ["policy", "init"])
    assert result.exit_code == 0, result.output
    assert path.is_file()
    assert "pii-airlock allow" in result.output
    again = runner.invoke(app, ["policy", "init"])
    assert again.exit_code == 0
    assert "already exists" in again.output


def test_allow_and_deny_update_policy(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    assert runner.invoke(app, ["allow", "Acme SA"]).exit_code == 0
    assert "already allowed" in runner.invoke(app, ["allow", "acme sa"]).output
    assert runner.invoke(app, ["deny", "Project Phoenix", "--as", "codename"]).exit_code == 0

    cfg = load_config(cwd=tmp_path)
    assert "Acme SA" in cfg.allow_list
    assert cfg.deny_list["CODENAME"] == ["Project Phoenix"]

    shown = runner.invoke(app, ["policy", "show"]).output
    assert "Acme SA" in shown
    assert "CODENAME: Project Phoenix" in shown


def test_allow_user_scope(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    assert runner.invoke(app, ["allow", "Jane Roe", "--scope", "user"]).exit_code == 0
    assert skill_path("user").is_file()
    assert not skill_path("project", tmp_path).exists()


def test_allow_reports_broken_policy(tmp_path, monkeypatch):
    path = _project(tmp_path, monkeypatch)
    path.parent.mkdir(parents=True)
    path.write_text("```yaml pii-airlock\nallow_list: [unclosed\n```\n", encoding="utf-8")
    result = runner.invoke(app, ["allow", "X"])
    assert result.exit_code == 1
    assert "invalid YAML" in result.output


def test_bad_scope_rejected(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    result = runner.invoke(app, ["allow", "X", "--scope", "team"])
    assert result.exit_code == 1


def test_action_sets_and_shows_entity_policy(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from pii_scrub.cli import app

    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    assert "IBAN_CODE -> redact" in runner.invoke(app, ["action", "iban_code", "redact"]).output
    assert "already redact" in runner.invoke(app, ["action", "IBAN_CODE", "redact"]).output
    bad = runner.invoke(app, ["action", "PERSON", "delete"])
    assert bad.exit_code == 1 and "not one of" in bad.output
    assert "action IBAN_CODE: redact" in runner.invoke(app, ["policy", "show"]).output
