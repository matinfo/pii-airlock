"""pii-airlock command-line interface."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import typer

from . import __version__
from .config import load_config
from .formats import MissingExtra, get_handler_class
from .mapping import Mapping

app = typer.Typer(
    add_completion=False,
    help="Local, reversible PII anonymizer built on Microsoft Presidio.",
    no_args_is_help=True,
)
hook_app = typer.Typer(help="Claude Code hook entry points (read JSON from stdin).")
app.add_typer(hook_app, name="hook")


def _version_cb(value: bool) -> None:
    if value:
        typer.echo(f"pii-airlock {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(
        False, "--version", callback=_version_cb, is_eager=True, help="Show version."
    ),
) -> None:
    pass


def _build_config(lang: str | None, threshold: float | None) -> object:
    overrides: dict = {}
    if lang:
        overrides["languages"] = [s.strip() for s in lang.split(",") if s.strip()]
    if threshold is not None:
        overrides["score_threshold"] = threshold
    return load_config(overrides)


def _read_input(file: Path | None, binary: bool) -> str | bytes:
    if file is None:
        return sys.stdin.buffer.read() if binary else sys.stdin.read()
    return file.read_bytes() if binary else file.read_text(encoding="utf-8")


def _write_output(out: Path | None, data: str | bytes) -> None:
    if out is None:
        if isinstance(data, bytes):
            sys.stdout.buffer.write(data)
        else:
            sys.stdout.write(data)
        return
    if isinstance(data, bytes):
        out.write_bytes(data)
    else:
        out.write_text(data, encoding="utf-8")
    typer.echo(f"Wrote {out}", err=True)


def _default_map_path(file: Path | None) -> Path:
    base = file.name if file else "stdin"
    return Path(f"{base}.pii-map.json")


@app.command()
def scrub(
    file: Path | None = typer.Argument(None, help="Input file; omit to read stdin."),
    lang: str | None = typer.Option(None, "--lang", help="Languages, e.g. 'fr,en'."),
    fmt: str = typer.Option("auto", "--format", help="Force a format (text/csv/json/docx/pdf)."),
    map_path: Path | None = typer.Option(None, "--map", help="Mapping file path."),
    no_map: bool = typer.Option(False, "--no-map", help="Irreversible: don't write a mapping."),
    threshold: float | None = typer.Option(None, "--threshold", help="Min confidence 0-1."),
    out: Path | None = typer.Option(None, "-o", "--out", help="Output file; omit for stdout."),
) -> None:
    """Replace PII with stable tokens, optionally saving a reversible mapping."""
    from .engine import ScrubEngine  # lazy: avoids loading Presidio for --help

    config = _build_config(lang, threshold)
    engine = ScrubEngine(config)

    handler_cls = get_handler_class(file, fmt)
    raw = _read_input(file, handler_cls.reads_binary)

    mapping = Mapping()
    language = config.languages[0]

    def _scrub_text(text: str) -> str:
        return engine.scrub(text, mapping, language)

    try:
        result = handler_cls(raw).scrub(_scrub_text)
    except MissingExtra as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None

    _write_output(out, result)

    if not no_map:
        target = map_path or _default_map_path(file)
        mapping.save(target)
        typer.echo(f"Mapping ({len(mapping)} entries) saved to {target}", err=True)


@app.command()
def restore(
    file: Path | None = typer.Argument(None, help="Scrubbed file; omit to read stdin."),
    map_path: Path = typer.Option(..., "--map", help="Mapping file from `scrub`."),
    out: Path | None = typer.Option(None, "-o", "--out", help="Output file; omit for stdout."),
) -> None:
    """Swap tokens back to their original values using a mapping file."""
    if not map_path.is_file():
        typer.echo(f"Mapping file not found: {map_path}", err=True)
        raise typer.Exit(code=1)
    mapping = Mapping.load(map_path)
    text = _read_input(file, binary=False)
    assert isinstance(text, str)
    _write_output(out, mapping.restore(text))


@app.command()
def detect(
    file: Path | None = typer.Argument(None, help="Input file; omit to read stdin."),
    lang: str | None = typer.Option(None, "--lang", help="Languages, e.g. 'fr,en'."),
    threshold: float | None = typer.Option(None, "--threshold", help="Min confidence 0-1."),
) -> None:
    """Dry run: list detected PII entities and spans without changing the text."""
    from .engine import ScrubEngine

    config = _build_config(lang, threshold)
    engine = ScrubEngine(config)
    text = _read_input(file, binary=False)
    assert isinstance(text, str)

    detections = engine.detect(text, config.languages[0])
    if not detections:
        typer.echo("No PII detected.")
        raise typer.Exit()
    for d in sorted(detections, key=lambda x: x.start):
        snippet = text[d.start : d.end].replace("\n", " ")
        typer.echo(f"{d.entity_type:<16} {d.score:.2f}  [{d.start}:{d.end}]  {snippet!r}")


def _has_pip() -> bool:
    """Whether this interpreter can install packages with pip.

    pipx venvs ship without pip, so `spacy download` (which shells out to pip)
    cannot install a model into them.
    """
    return importlib.util.find_spec("pip") is not None


def _model_installed(model: str) -> bool:
    """Check, in a fresh interpreter, whether `model` is importable.

    A subprocess avoids stale import caches right after an install attempt.
    """
    code = f"import importlib.util, sys; sys.exit(0 if importlib.util.find_spec({model!r}) else 1)"
    return subprocess.call([sys.executable, "-c", code]) == 0


def _spacy_wheel_url(model: str) -> str | None:
    """Best-effort resolve the direct wheel URL for a spaCy model.

    Never raises: returns None if spaCy's compatibility table can't be reached
    or its internals changed, so callers can fall back to generic guidance.
    """
    try:
        from spacy.cli.download import get_compatibility, get_version

        version = get_version(model, get_compatibility())
        return (
            "https://github.com/explosion/spacy-models/releases/download/"
            f"{model}-{version}/{model}-{version}-py3-none-any.whl"
        )
    except Exception:
        return None


def _inject_hint(models: list[str]) -> None:
    """Print exact commands to install models into a pip-less (e.g. pipx) env."""
    typer.echo(
        "This interpreter has no pip (typical for a pipx install), so spaCy "
        "models can't be downloaded the usual way.\nInstall each model directly "
        "— for a pipx install, use:",
        err=True,
    )
    for model in models:
        url = _spacy_wheel_url(model)
        if url:
            typer.echo(f'  pipx inject pii-airlock "{url}"', err=True)
        else:
            typer.echo(
                f"  pipx inject pii-airlock  # wheel for {model}: "
                "https://github.com/explosion/spacy-models/releases",
                err=True,
            )


def _configured_models(config: object) -> list[str]:
    return [config.models[lc] for lc in config.languages if lc in config.models]


def _missing_proxy_deps() -> list[str]:
    required = ("httpx", "starlette", "uvicorn")
    return [name for name in required if importlib.util.find_spec(name) is None]


def _env_export_examples(host: str, port: int) -> list[str]:
    url = f"http://{host}:{port}/openai"
    if os.name == "nt":
        return [
            f'$env:OPENAI_BASE_URL = "{url}"   # PowerShell',
            f"set OPENAI_BASE_URL={url}        # cmd.exe",
        ]
    return [
        f"export OPENAI_BASE_URL={url}        # bash/zsh",
        f"set -x OPENAI_BASE_URL {url}        # fish",
    ]


@app.command("download-models")
def download_models(
    lang: str | None = typer.Option(None, "--lang", help="Languages, e.g. 'fr,en'."),
) -> None:
    """Download the spaCy models configured for the selected languages."""
    config = _build_config(lang, None)
    models = _configured_models(config)
    if not models:
        typer.echo("No models configured.", err=True)
        raise typer.Exit(code=1)

    # pipx and other pip-less envs can't install via `spacy download`; guide only
    # for models that are missing in the current interpreter.
    if not _has_pip():
        missing = [model for model in models if not _model_installed(model)]
        if missing:
            _inject_hint(missing)
            raise typer.Exit(code=1)
        typer.echo("Done.", err=True)
        return

    failed: list[str] = []
    for model in models:
        typer.echo(f"Downloading {model} ...", err=True)
        rc = subprocess.call([sys.executable, "-m", "spacy", "download", model])
        # Verify: some installers report success without placing the model here.
        if rc != 0 or not _model_installed(model):
            failed.append(model)

    if failed:
        typer.echo(f"Failed to install: {', '.join(failed)}", err=True)
        for model in failed:
            url = _spacy_wheel_url(model)
            if url:
                typer.echo(f'  Try:  {sys.executable} -m pip install "{url}"', err=True)
        raise typer.Exit(code=1)
    typer.echo("Done.", err=True)


@app.command()
def init(
    host: str = typer.Option("127.0.0.1", "--host", help="Gateway bind address."),
    port: int = typer.Option(8745, "--port", help="Gateway bind port."),
    skip_models: bool = typer.Option(
        False, "--skip-models", help="Skip model install/check during setup."
    ),
) -> None:
    """Guided first-time setup for the gateway workflow."""
    typer.echo("pii-airlock setup", err=True)
    typer.echo("-----------------", err=True)

    ok = True
    missing_deps = _missing_proxy_deps()
    if missing_deps:
        ok = False
        typer.echo(f"[needs action] Missing gateway deps: {', '.join(missing_deps)}", err=True)
        typer.echo("  Run: pipx inject pii-airlock 'pii-airlock[proxy]'", err=True)
    else:
        typer.echo("[ok] Gateway dependencies installed", err=True)

    config = _build_config(None, None)
    models = _configured_models(config)
    if not models:
        ok = False
        typer.echo("[needs action] No spaCy models configured.", err=True)
    elif skip_models:
        missing_models = [model for model in models if not _model_installed(model)]
        if missing_models:
            ok = False
            typer.echo(
                f"[needs action] Missing models: {', '.join(missing_models)} "
                "(run `pii-airlock download-models`)",
                err=True,
            )
        else:
            typer.echo("[ok] Required spaCy models already installed", err=True)
    else:
        try:
            download_models(None)
            typer.echo("[ok] spaCy model setup complete", err=True)
        except typer.Exit as exc:
            ok = False
            if exc.exit_code not in (0, None):
                typer.echo("[needs action] Model setup needs manual completion.", err=True)

    typer.echo("\nNext commands:", err=True)
    typer.echo("  pii-airlock proxy", err=True)
    for line in _env_export_examples(host, port):
        typer.echo(f"  {line}", err=True)

    if ok:
        typer.echo("\nSetup complete.", err=True)
    else:
        typer.echo(
            "\nSetup incomplete. Run the commands above, then retry `pii-airlock init`.",
            err=True,
        )
        raise typer.Exit(code=1)


@app.command()
def doctor() -> None:
    """Health checks for a local pii-airlock installation."""
    config = _build_config(None, None)
    models = _configured_models(config)
    missing_models = [m for m in models if not _model_installed(m)]
    missing_deps = _missing_proxy_deps()
    has_pip = _has_pip()
    m = Mapping()
    mapping_ok = m.restore(m.token_for("PERSON", "A")) == "A"

    checks: list[tuple[str, bool, str]] = [
        ("Python", True, sys.executable),
        ("pip available", has_pip, "found" if has_pip else "missing"),
        (
            "gateway deps",
            not missing_deps,
            "ok" if not missing_deps else f"missing: {', '.join(missing_deps)}",
        ),
        (
            "configured models",
            bool(models),
            ", ".join(models) if models else "none",
        ),
        (
            "installed models",
            not missing_models,
            "ok" if not missing_models else f"missing: {', '.join(missing_models)}",
        ),
        (
            "mapping roundtrip",
            mapping_ok,
            "ok",
        ),
    ]

    failed = False
    for name, ok, detail in checks:
        state = "ok" if ok else "fail"
        typer.echo(f"[{state}] {name}: {detail}", err=True)
        failed = failed or not ok

    if failed:
        raise typer.Exit(code=1)


@app.command()
def proxy(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address."),
    port: int = typer.Option(8745, "--port", help="Bind port."),
    lang: str | None = typer.Option(None, "--lang", help="Languages, e.g. 'fr,en'."),
    openai_url: str | None = typer.Option(None, "--openai-url", help="Override OpenAI upstream."),
    anthropic_url: str | None = typer.Option(
        None, "--anthropic-url", help="Override Anthropic upstream."
    ),
    gemini_url: str | None = typer.Option(None, "--gemini-url", help="Override Gemini upstream."),
) -> None:
    """Run the local privacy gateway (reverse proxy: scrub out, restore in).

    Point a client at it via its base URL, e.g.:
      OPENAI_BASE_URL=http://127.0.0.1:8745/openai
      ANTHROPIC_BASE_URL=http://127.0.0.1:8745/anthropic
    """
    from .proxy import run

    config = _build_config(lang, None)
    upstreams = {}
    if openai_url:
        upstreams["openai"] = openai_url
    if anthropic_url:
        upstreams["anthropic"] = anthropic_url
    if gemini_url:
        upstreams["gemini"] = gemini_url

    typer.echo(f"pii-airlock gateway on http://{host}:{port}  (languages: {config.languages})",
               err=True)
    typer.echo("  OpenAI    -> $OPENAI_BASE_URL    = "
               f"http://{host}:{port}/openai", err=True)
    typer.echo("  Anthropic -> $ANTHROPIC_BASE_URL = "
               f"http://{host}:{port}/anthropic", err=True)
    typer.echo("  Gemini    -> base path           = "
               f"http://{host}:{port}/gemini", err=True)
    run(host=host, port=port, config=config, upstreams=upstreams or None)


@app.command("install-hook")
def install_hook(
    event: str = typer.Option("both", "--event", help="both | tool | prompt"),
    scope: str = typer.Option("project", "--scope", help="project | user"),
) -> None:
    """Register the Claude Code hook(s) in settings.json."""
    from .hookinstall import install

    try:
        path, added = install(event, scope)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None
    if added:
        typer.echo(f"Installed hooks {', '.join(added)} in {path}")
    else:
        typer.echo(f"Hooks already present in {path} — nothing to do.")


@hook_app.command("pre-tool-use")
def hook_pre_tool_use() -> None:
    """PreToolUse hook entry point (reads event JSON from stdin)."""
    from hooks._common import run_pre_tool_use

    run_pre_tool_use()


@hook_app.command("user-prompt-submit")
def hook_user_prompt_submit() -> None:
    """UserPromptSubmit hook entry point (reads event JSON from stdin)."""
    from hooks._common import run_user_prompt_submit

    run_user_prompt_submit()


if __name__ == "__main__":
    app()
