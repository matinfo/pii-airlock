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
    monkeypatch.setattr(cli, "_model_installed", lambda model: False)
    monkeypatch.setattr(cli, "_spacy_wheel_url", lambda model: f"https://example.test/{model}.whl")

    with pytest.raises(cli.typer.Exit) as exc:
        cli.download_models(None)

    assert exc.value.exit_code == 1
    rendered = "\n".join(text for text, _ in out)
    assert "has no pip" in rendered
    assert 'pipx inject pii-airlock "https://example.test/en_model.whl"' in rendered


def test_download_models_pipless_succeeds_if_models_already_installed(monkeypatch):
    out = _capture_echo(monkeypatch)
    monkeypatch.setattr(
        cli, "_build_config", lambda lang, threshold: _fake_config({"en": "en_model"})
    )
    monkeypatch.setattr(cli, "_has_pip", lambda: False)
    monkeypatch.setattr(cli, "_model_installed", lambda model: True)
    monkeypatch.setattr(
        cli, "_inject_hint", lambda models: (_ for _ in ()).throw(AssertionError("should not hint"))
    )

    cli.download_models(None)

    assert out[-1][0] == "Done."


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


def test_init_reports_ready(monkeypatch):
    out = _capture_echo(monkeypatch)
    monkeypatch.setattr(
        cli, "_build_config", lambda lang, threshold: _fake_config({"en": "en_model"})
    )
    monkeypatch.setattr(cli, "_missing_proxy_deps", lambda: [])
    monkeypatch.setattr(cli, "download_models", lambda lang: None)
    monkeypatch.setattr(
        cli, "_env_export_examples", lambda host, port: ["export OPENAI_BASE_URL=..."]
    )

    cli.init(host="127.0.0.1", port=8745, skip_models=False)

    rendered = "\n".join(text for text, _ in out)
    assert "Setup complete." in rendered
    assert "pii-airlock proxy" in rendered


def test_doctor_exits_nonzero_when_missing_requirements(monkeypatch):
    out = _capture_echo(monkeypatch)
    monkeypatch.setattr(
        cli, "_build_config", lambda lang, threshold: _fake_config({"en": "en_model"})
    )
    monkeypatch.setattr(cli, "_has_pip", lambda: False)
    monkeypatch.setattr(cli, "_missing_proxy_deps", lambda: ["httpx"])
    monkeypatch.setattr(cli, "_model_installed", lambda model: False)

    with pytest.raises(cli.typer.Exit) as exc:
        cli.doctor()

    assert exc.value.exit_code == 1
    rendered = "\n".join(text for text, _ in out)
    assert "[fail] gateway deps:" in rendered
    assert "[fail] installed models:" in rendered
