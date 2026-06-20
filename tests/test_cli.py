"""CLI tests for download-models behavior in pip and pip-less environments."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

import pii_scrub.cli as cli


def _fake_config(models: dict[str, str], languages: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(models=models, languages=languages or list(models.keys()))


def _capture_echo(monkeypatch) -> list[tuple[str, bool]]:
    out: list[tuple[str, bool]] = []

    def _echo(message="", err=False, **kwargs):
        out.append((str(message), bool(err)))

    monkeypatch.setattr(cli.typer, "echo", _echo)
    return out


def test_download_models_pipless_prints_pipx_inject_and_exits(monkeypatch):
    out = _capture_echo(monkeypatch)
    monkeypatch.setattr(
        cli, "_build_config", lambda lang, threshold: _fake_config({"en": "en_model"})
    )
    monkeypatch.setattr(cli, "_has_pip", lambda: False)
    monkeypatch.setattr(cli, "_spacy_wheel_url", lambda model: f"https://example.test/{model}.whl")
    monkeypatch.setattr(
        cli.subprocess,
        "call",
        lambda args: (_ for _ in ()).throw(AssertionError("subprocess.call should not run")),
    )

    with pytest.raises(cli.typer.Exit) as exc:
        cli.download_models(None)

    assert exc.value.exit_code == 1
    rendered = "\n".join(text for text, _ in out)
    assert "has no pip" in rendered
    assert 'pipx inject pii-airlock "https://example.test/en_model.whl"' in rendered


def test_download_models_with_pip_downloads_and_succeeds(monkeypatch):
    out = _capture_echo(monkeypatch)
    monkeypatch.setattr(
        cli, "_build_config", lambda lang, threshold: _fake_config({"en": "en_model"})
    )
    monkeypatch.setattr(cli, "_has_pip", lambda: True)
    monkeypatch.setattr(cli, "_model_installed", lambda model: True)

    calls: list[list[str]] = []

    def _call(args):
        calls.append(args)
        return 0

    monkeypatch.setattr(cli.subprocess, "call", _call)

    cli.download_models(None)

    assert out[-1][0] == "Done."
    assert calls == [[sys.executable, "-m", "spacy", "download", "en_model"]]


def test_download_models_with_pip_reports_failed_models(monkeypatch):
    out = _capture_echo(monkeypatch)
    monkeypatch.setattr(
        cli, "_build_config", lambda lang, threshold: _fake_config({"en": "en_model"})
    )
    monkeypatch.setattr(cli, "_has_pip", lambda: True)
    monkeypatch.setattr(cli.subprocess, "call", lambda args: 0)
    monkeypatch.setattr(cli, "_model_installed", lambda model: False)
    monkeypatch.setattr(cli, "_spacy_wheel_url", lambda model: f"https://example.test/{model}.whl")

    with pytest.raises(cli.typer.Exit) as exc:
        cli.download_models(None)

    assert exc.value.exit_code == 1
    rendered = "\n".join(text for text, _ in out)
    assert "Failed to install: en_model" in rendered
    expected = f'Try:  {sys.executable} -m pip install "https://example.test/en_model.whl"'
    assert expected in rendered
