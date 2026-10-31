"""CLI tests for download-models behavior in pip and pip-less environments."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

import pii_scrub.cli as cli


def _fake_config(models: dict[str, str], languages: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(models=models, languages=languages or list(models.keys()),
                           hook_daemon="off", ner_backend="spacy")


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


def test_scrub_refuses_a_file_with_a_blocked_entity(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from typer.testing import CliRunner

    from pii_scrub.engine import ScrubEngine

    def analyze(text, language, entities):
        i = text.find("jean@acme.fr")
        return [] if i < 0 else [SimpleNamespace(entity_type="EMAIL_ADDRESS", start=i,
                                                 end=i + 12, score=1.0)]

    # No spaCy model needed (nor the machine's own config): the analyzer is stubbed.
    monkeypatch.setattr(ScrubEngine, "_analyzer", SimpleNamespace(analyze=analyze))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    (tmp_path / ".pii-airlock.yaml").write_text("entity_actions: {EMAIL_ADDRESS: block}\n")
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "in.txt"
    src.write_text("mail jean@acme.fr please")
    result = CliRunner().invoke(cli.app, ["scrub", str(src), "--no-map", "-o",
                                         str(tmp_path / "out.txt")])
    assert result.exit_code == 1 and "EMAIL_ADDRESS×1" in result.output
    assert not (tmp_path / "out.txt").exists()


def test_header_profiled_csv_columns_obey_entity_actions(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    (tmp_path / ".pii-airlock.yaml").write_text(
        "entity_actions: {EMAIL_ADDRESS: redact}\nlanguages: [en]\nmodels: {en: x}\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("pii_scrub.engine.ScrubEngine._analyzer",
                        __import__("types").SimpleNamespace(analyze=lambda **_k: []))
    src = tmp_path / "p.csv"
    src.write_text("id,email\n1,jean@acme.fr\n")
    out = tmp_path / "o.csv"
    result = CliRunner().invoke(cli.app, ["scrub", str(src), "--map", str(tmp_path / "m.json"),
                                         "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert "[EMAIL_ADDRESS]" in out.read_text()
    assert "jean@acme.fr" not in (tmp_path / "m.json").read_text()


def _scrub_email(tmp_path, monkeypatch, *extra):
    """Run `scrub` on a one-email file with the analyzer stubbed; returns the paths."""
    from types import SimpleNamespace

    from typer.testing import CliRunner

    from pii_scrub.engine import ScrubEngine

    def analyze(text, **_k):
        from presidio_analyzer import RecognizerResult

        i = text.find("jean@acme.fr")
        return [RecognizerResult("EMAIL_ADDRESS", i, i + 12, 1.0)] if i >= 0 else []

    monkeypatch.setattr(ScrubEngine, "_analyzer", SimpleNamespace(analyze=analyze))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    (tmp_path / ".pii-airlock.yaml").write_text("languages: [en]\nmodels: {en: x}\n")
    monkeypatch.chdir(tmp_path)
    src, out, mp = tmp_path / "in.txt", tmp_path / "out.txt", tmp_path / "m.pii-map.json"
    src.write_text("mail jean@acme.fr please")
    result = CliRunner().invoke(cli.app, ["scrub", str(src), "--map", str(mp), "-o", str(out),
                                         *extra])
    assert result.exit_code == 0, result.output
    return out, mp


def test_scrub_map_is_plain_json_by_default(tmp_path, monkeypatch):
    _, mp = _scrub_email(tmp_path, monkeypatch)
    assert "jean@acme.fr" in mp.read_text()


def test_encrypt_map_round_trips_through_restore(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    out, mp = _scrub_email(tmp_path, monkeypatch, "--encrypt-map")
    assert b"jean@acme.fr" not in mp.read_bytes()
    restored = CliRunner().invoke(cli.app, ["restore", str(out), "--map", str(mp)])
    assert restored.exit_code == 0, restored.output
    assert "jean@acme.fr" in restored.output


def test_restore_reports_a_map_encrypted_with_another_key(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    out, mp = _scrub_email(tmp_path, monkeypatch, "--encrypt-map")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "other-machine"))
    from pii_scrub import token_key

    token_key._master_key.cache_clear()
    result = CliRunner().invoke(cli.app, ["restore", str(out), "--map", str(mp)])
    assert result.exit_code == 1 and "cannot decrypt" in result.output
