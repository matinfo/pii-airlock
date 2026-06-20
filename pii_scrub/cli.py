"""pii-scrub command-line interface."""

from __future__ import annotations

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
        typer.echo(f"pii-scrub {__version__}")
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


@app.command("download-models")
def download_models(
    lang: str | None = typer.Option(None, "--lang", help="Languages, e.g. 'fr,en'."),
) -> None:
    """Download the spaCy models configured for the selected languages."""
    config = _build_config(lang, None)
    models = [config.models[lc] for lc in config.languages if lc in config.models]
    if not models:
        typer.echo("No models configured.", err=True)
        raise typer.Exit(code=1)
    for model in models:
        typer.echo(f"Downloading {model} ...", err=True)
        rc = subprocess.call([sys.executable, "-m", "spacy", "download", model])
        if rc != 0:
            typer.echo(f"Failed to download {model}", err=True)
            raise typer.Exit(code=rc)
    typer.echo("Done.", err=True)


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
