"""Keep tests away from the user's real state (token key, mappings, config, hooks)."""

import pytest


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("COPILOT_HOME", str(tmp_path / "copilot"))
    monkeypatch.setattr("pii_scrub.config.USER_FILE", tmp_path / "user-config.yaml")
    monkeypatch.setattr("pii_scrub.hookinstall.USER_SETTINGS",
                        tmp_path / "claude-home" / "settings.json")


@pytest.fixture(autouse=True)
def hooks_always_active(monkeypatch, request):
    """Hook tests run in tmp dirs with no project home; test_project.py checks the real rule."""
    if request.module.__name__.endswith("test_project"):
        return
    monkeypatch.setattr("pii_scrub.hooks._common.is_active", lambda *_a: True)


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A guarded project (as after `pii-airlock init`), as the current directory."""
    from pii_scrub import project as proj
    from pii_scrub.trust import trust

    root = tmp_path / "proj"
    root.mkdir()
    proj.init_project(root)
    trust(root)
    monkeypatch.chdir(root)
    return root
