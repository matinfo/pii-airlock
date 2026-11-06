"""CLI tests for the policy commands (allow / deny / action / status)."""

from __future__ import annotations

from typer.testing import CliRunner

from pii_scrub import config as config_mod
from pii_scrub.cli import app
from pii_scrub.config import load_config
from pii_scrub.project import config_path

runner = CliRunner()


def test_allow_and_deny_update_policy(project):
    assert runner.invoke(app, ["allow", "Acme SA"]).exit_code == 0
    assert "already allowed" in runner.invoke(app, ["allow", "acme sa"]).output
    assert runner.invoke(app, ["deny", "Project Phoenix", "--as", "codename"]).exit_code == 0

    cfg = load_config(cwd=project)
    assert "Acme SA" in cfg.allow_list
    assert cfg.deny_list["CODENAME"] == ["Project Phoenix"]

    shown = runner.invoke(app, ["status"]).output
    assert "Acme SA" in shown
    assert "CODENAME: Project Phoenix" in shown


def test_policy_commands_work_from_a_subdirectory(project):
    sub = project / "src" / "deep"
    sub.mkdir(parents=True)
    import os

    os.chdir(sub)
    assert runner.invoke(app, ["allow", "Acme"]).exit_code == 0
    assert "Acme" in load_config(cwd=sub).allow_list


def test_allow_outside_a_project_asks_for_init(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["allow", "X"])
    assert result.exit_code == 1 and "pii-airlock init" in result.output


def test_allow_user_scope(project):
    assert runner.invoke(app, ["allow", "Jane Roe", "--scope", "user"]).exit_code == 0
    assert "Jane Roe" in config_mod.USER_FILE.read_text()
    assert "Jane Roe" not in config_path(project).read_text()


def test_allow_reports_broken_policy(project):
    config_path(project).write_text("allow_list: [unclosed\n", encoding="utf-8")
    result = runner.invoke(app, ["allow", "X"])
    assert result.exit_code == 1
    assert "invalid YAML" in result.output


def test_bad_scope_rejected(project):
    assert runner.invoke(app, ["allow", "X", "--scope", "team"]).exit_code == 1


def test_action_sets_and_shows_entity_policy(project):
    assert "IBAN_CODE -> redact" in runner.invoke(app, ["action", "iban_code", "redact"]).output
    assert "already redact" in runner.invoke(app, ["action", "IBAN_CODE", "redact"]).output
    bad = runner.invoke(app, ["action", "PERSON", "delete"])
    assert bad.exit_code == 1 and "not one of" in bad.output
    assert "IBAN_CODE: redact" in runner.invoke(app, ["status"]).output
