import io
import json

from typer.testing import CliRunner

from pii_scrub import hookinstall, project
from pii_scrub.cli import app
from pii_scrub.hooks import _common

runner = CliRunner()


def test_home_layout_and_gitignore(tmp_path):
    assert project.init_project(tmp_path) is True
    assert project.init_project(tmp_path) is False
    home = tmp_path / ".pii-airlock"
    assert (home / "config.yaml").is_file() and (home / "maps").is_dir()
    ignore = (home / ".gitignore").read_text()
    assert "*\n" in ignore and "!config.yaml" in ignore


def test_found_from_subdirectory(tmp_path):
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    assert project.find_project(sub) is None
    project.init_project(tmp_path)
    assert project.find_project(sub) == tmp_path.resolve()


def test_pause_resume_and_activation(tmp_path):
    assert not project.is_active(tmp_path, "project")
    assert project.is_active(tmp_path, "always")
    project.init_project(tmp_path)
    assert project.is_active(tmp_path, "project")
    assert project.pause(tmp_path) and not project.pause(tmp_path)
    assert not project.is_active(tmp_path, "always")  # an explicit pause wins
    assert project.resume(tmp_path)
    project.pause(tmp_path)
    project.init_project(tmp_path)  # init resumes
    assert project.is_active(tmp_path, "project")


def _pre_tool_use(monkeypatch, cwd):
    seen = []
    monkeypatch.setattr(_common, "_analyze", lambda c, e, texts: seen.extend(texts) or [])
    event = json.dumps({"tool_name": "Bash", "cwd": str(cwd),
                        "tool_input": {"command": "mail jean@acme.fr"}})
    monkeypatch.setattr("sys.stdin", io.StringIO(event))
    _common.run_pre_tool_use()
    return seen


def test_hooks_run_only_in_guarded_projects(tmp_path, monkeypatch):
    assert _pre_tool_use(monkeypatch, tmp_path) == []
    project.init_project(tmp_path)
    assert _pre_tool_use(monkeypatch, tmp_path) == ["mail jean@acme.fr"]
    project.pause(tmp_path)
    assert _pre_tool_use(monkeypatch, tmp_path) == []


def test_session_start_gives_claude_the_rules_only_when_guarded(tmp_path, monkeypatch, capsys):
    def run():
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"cwd": str(tmp_path)})))
        _common.run_session_start()
        return capsys.readouterr().out

    assert run() == ""
    project.init_project(tmp_path)
    assert "guarded by pii-airlock" in run() and ".pii-airlock/maps/" in run()


def test_init_installs_user_hooks_once_and_trusts_its_own_config(tmp_path, monkeypatch):
    hookinstall.USER_SETTINGS.parent.mkdir(parents=True)  # Claude Code is installed
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init", "--skip-models"])
    assert "Guarding" in result.output and "Claude Code: hooks installed" in result.output
    assert hookinstall.claude_hook_installed("user")
    assert not (tmp_path / ".claude").exists()  # nothing written into the repo
    from pii_scrub.trust import is_trusted

    assert is_trusted(tmp_path)
    again = runner.invoke(app, ["init", "--skip-models"])
    assert "Already guarding" in again.output and "hooks present" in again.output


def test_init_never_trusts_a_config_shipped_with_the_repo(tmp_path, monkeypatch):
    project.init_project(tmp_path)
    project.config_path(tmp_path).write_text("hook_on_error: open\n")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init", "--no-hooks", "--skip-models"])
    assert "needs review" in result.output


def test_init_skips_hooks_when_the_plugin_is_enabled(tmp_path, monkeypatch):
    settings = hookinstall.USER_SETTINGS
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"enabledPlugins": {"pii-airlock@pii-airlock": True}}))
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init", "--skip-models"])
    assert "pii-airlock plugin" in result.output
    assert not hookinstall.claude_hook_installed("user")


def test_off_on_status(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert "not a guarded project" in runner.invoke(app, ["status"]).output
    assert runner.invoke(app, ["off"]).exit_code == 1
    project.init_project(tmp_path)
    assert "on " in runner.invoke(app, ["status"]).output
    assert "Paused" in runner.invoke(app, ["off"]).output
    assert "PAUSED" in runner.invoke(app, ["status"]).output
    assert (tmp_path / ".pii-airlock" / "config.yaml").is_file()  # policy kept
    assert "again" in runner.invoke(app, ["on"]).output
