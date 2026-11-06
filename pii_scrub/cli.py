"""pii-airlock command-line interface."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

import typer

from . import __version__, mapping_crypto
from .config import load_config
from .formats import MissingExtra, get_handler_class
from .mapping import Mapping
from .token_key import new_mapping

app = typer.Typer(
    add_completion=False,
    help="Local, reversible PII anonymizer built on Microsoft Presidio.",
    no_args_is_help=True,
)
hook_app = typer.Typer(help="Claude Code hook entry points (read JSON from stdin).")
app.add_typer(hook_app, name="hook")
daemon_app = typer.Typer(
    help="Hook daemon: keeps the models loaded so hooks answer in milliseconds."
)
app.add_typer(daemon_app, name="daemon")


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


def _policy_tokenizer(config, mapping):
    """`mapping.token_for` that obeys `entity_actions` (CSV columns chosen by header)."""
    from .engine import PolicyBlocked

    def tokenize(entity: str, value: str) -> str:
        action = config.action_for(entity)
        if action == "block":
            raise PolicyBlocked(Counter({entity: 1}))
        if action == "allow":
            return value
        if action == "redact":
            return f"[{entity}]"
        return mapping.token_for(entity, value)

    return tokenize


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
    return _maps_home() / f"{base}.pii-map.json"


def _maps_home() -> Path:
    """Where `scrub` keeps mappings: the project's .pii-airlock/maps/, else the state dir.

    Never next to the file: mapping files hold real PII and must not be committed."""
    from .mapping_store import default_state_dir
    from .project import find_project, maps_dir, private_dir

    root = find_project()
    return private_dir(maps_dir(root) if root else default_state_dir() / "maps")


@app.command()
def scrub(
    file: Path | None = typer.Argument(None, help="Input file; omit to read stdin."),
    lang: str | None = typer.Option(None, "--lang", help="Languages, e.g. 'fr,en'."),
    fmt: str = typer.Option("auto", "--format", help="Force a format (text/csv/json/docx/pdf)."),
    map_path: Path | None = typer.Option(None, "--map", help="Mapping file path."),
    no_map: bool = typer.Option(False, "--no-map", help="Irreversible: don't write a mapping."),
    encrypt_map: bool = typer.Option(
        False, "--encrypt-map",
        help="Encrypt the mapping file with this machine's key (restore needs the same key).",
    ),
    threshold: float | None = typer.Option(None, "--threshold", help="Min confidence 0-1."),
    out: Path | None = typer.Option(None, "-o", "--out", help="Output file; omit for stdout."),
) -> None:
    """Replace PII with stable tokens, optionally saving a reversible mapping."""
    # lazy: avoids loading Presidio for --help
    from .engine import PolicyBlocked, ScrubEngine, collect_texts

    config = _build_config(lang, threshold)
    handler_cls = get_handler_class(file, fmt)
    raw = _read_input(file, handler_cls.reads_binary)

    mapping = new_mapping(config)

    def run(transform):
        return handler_cls(raw).scrub(transform, _policy_tokenizer(config, mapping))

    try:
        if handler_cls.many_texts and config.analysis_cache_size > 0:
            # Dry run with an identity tokenizer: lists the cells to analyze
            # (header-profiled columns need none) without minting tokens.
            texts = collect_texts(lambda grab: handler_cls(raw).scrub(grab, lambda _e, v: v))
            # One-shot process: hold the whole file's findings, not just the default.
            size = max(config.analysis_cache_size, len(texts) * len(config.languages))
            engine = ScrubEngine(replace(config, analysis_cache_size=size))
            # A value found in any cell is scrubbed in every cell.
            result = engine.scrub_all(run, mapping, texts)
        else:
            engine = ScrubEngine(config)
            result = run(lambda t: engine.scrub(t, mapping))
    except MissingExtra as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None
    except PolicyBlocked as exc:
        typer.echo(f"Not scrubbed, nothing written: {exc}.", err=True)
        raise typer.Exit(code=1) from None

    _write_output(out, result)

    if not no_map:
        target = map_path or _default_map_path(file)
        encrypt = encrypt_map or map_path is None  # the default location is always encrypted
        key = mapping_crypto.default_key() if encrypt else None
        mapping.save(target, encrypt_key=key)
        kind = "Encrypted mapping" if encrypt else "Mapping"
        typer.echo(f"{kind} ({len(mapping)} entries) saved to {target}", err=True)


def _load_map(path: Path) -> Mapping:
    """Load a mapping file; an encrypted one is opened with this machine's key."""
    with path.open("rb") as fh:
        sealed = mapping_crypto.is_sealed(fh.read(len(mapping_crypto.MAGIC)))
    return Mapping.load(path, encrypt_key=mapping_crypto.default_key() if sealed else None)


@app.command()
def restore(
    file: Path | None = typer.Argument(None, help="Scrubbed file; omit to read stdin."),
    map_path: Path | None = typer.Option(
        None, "--map", help="Mapping file from `scrub`; default: every mapping of this project."),
    out: Path | None = typer.Option(None, "-o", "--out", help="Output file; omit for stdout."),
) -> None:
    """Swap tokens back to their original values."""
    if map_path is not None and not map_path.is_file():
        typer.echo(f"Mapping file not found: {map_path}", err=True)
        raise typer.Exit(code=1)
    # Newest first: with sequential tokens (<PERSON_1>) the latest scrub wins; stable
    # tokens are unique per value, so the order does not matter.
    paths = [map_path] if map_path else sorted(
        _maps_home().glob("*.pii-map.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not paths:
        typer.echo(f"No mapping in {_maps_home()}: run `scrub` first, or pass --map.", err=True)
        raise typer.Exit(code=1)
    try:
        mappings = [_load_map(path) for path in paths]
    except mapping_crypto.MappingDecryptError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None
    text = _read_input(file, binary=False)
    assert isinstance(text, str)
    for mapping in mappings:
        text = mapping.restore(text)
    _write_output(out, text)


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

    detections = engine.detect(text)
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


def _download_gliner(model: str) -> None:
    from .gliner_backend import load_model

    typer.echo(f"Downloading GLiNER model {model} ...", err=True)
    try:
        load_model(model)  # fetched into the Hugging Face cache
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None
    typer.echo("Done.", err=True)


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
    """Download the models configured for the selected languages."""
    config = _build_config(lang, None)
    if config.ner_backend == "gliner":
        _download_gliner(config.gliner_model)
        return
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
    hooks: bool = typer.Option(True, "--hooks/--no-hooks",
                               help="Install the user-level hooks for Claude Code / Copilot."),
    skip_models: bool = typer.Option(
        False, "--skip-models", help="Skip model install/check during setup."
    ),
    host: str = typer.Option("127.0.0.1", "--host", help="Gateway address shown in the hints."),
    port: int = typer.Option(8745, "--port", help="Gateway port shown in the hints."),
) -> None:
    """Guard this project: create .pii-airlock/, install the hooks, check the models."""
    from .project import config_path, init_project
    from .trust import is_trusted, trust

    root = Path.cwd()
    shipped = config_path(root).is_file() and not is_trusted(root)
    created = init_project(root)
    if not shipped:
        trust(root)  # the config is yours (new, or already trusted)
    typer.echo(f"[ok] {'Guarding' if created else 'Already guarding'} {root} "
               f"(policy: .pii-airlock/config.yaml)", err=True)
    if shipped:
        typer.echo("[needs review] .pii-airlock/config.yaml came with the repo: only settings "
                   "that tighten protection apply until you run `pii-airlock trust`.", err=True)

    ok = True
    if hooks:
        for line in _ensure_hooks():
            typer.echo(line, err=True)

    config = _build_config(None, None)
    models = _configured_models(config)
    missing = [m for m in models if not _model_installed(m)]
    if not missing:
        typer.echo("[ok] Detection models installed", err=True)
    elif skip_models:
        ok = False
        typer.echo(f"[needs action] Missing models: {', '.join(missing)} "
                   "(run `pii-airlock download-models`)", err=True)
    else:
        try:
            download_models(None)
            typer.echo("[ok] Detection models installed", err=True)
        except typer.Exit as exc:
            if exc.exit_code not in (0, None):
                ok = False
                typer.echo("[needs action] Model setup needs manual completion.", err=True)

    typer.echo("\nOptional, for chat clients (Cursor, Codex, SDKs): the gateway", err=True)
    if _missing_proxy_deps():
        typer.echo("  pipx inject pii-airlock 'pii-airlock[proxy]'", err=True)
    typer.echo("  pii-airlock proxy", err=True)
    for line in _env_export_examples(host, port)[:1]:
        typer.echo(f"  {line}", err=True)

    if not ok:
        typer.echo("\nAlmost there: fix the [needs action] lines, then run "
                   "`pii-airlock status`.", err=True)
        raise typer.Exit(code=1)
    typer.echo("\nDone. `pii-airlock status` shows the setup; `pii-airlock off` pauses it here.",
               err=True)


def _ensure_hooks() -> list[str]:
    """Install the user-level hooks for the agents found on this machine (idempotent).

    User level, because they stay silent outside guarded projects: one install, then
    `pii-airlock init` per project. Nothing is written into the repo.
    """
    from . import hookinstall as hi

    lines = []
    if hi.claude_plugin_enabled():
        lines.append("[ok] Claude Code: pii-airlock plugin")
    elif hi.claude_present():
        _, added = hi.install("both", "user")
        lines.append(f"[ok] Claude Code: hooks {'installed' if added else 'present'} "
                     f"in {hi.settings_path('user')}")
    if hi.copilot_present():
        path, changed = hi.install_copilot("user")
        lines.append(f"[ok] GitHub Copilot: hook {'installed' if changed else 'present'} in {path}")
    if not lines:
        lines.append("[info] No Claude Code or Copilot found: hooks not installed. "
                     "Use the gateway, or rerun `pii-airlock init` after installing one.")
    return lines


def _require_project() -> Path:
    from .project import find_project

    root = find_project()
    if root is None:
        typer.echo("This directory is not guarded (no .pii-airlock/ here or above). "
                   "Run `pii-airlock init`.", err=True)
        raise typer.Exit(code=1)
    return root


@app.command()
def off() -> None:
    """Pause pii-airlock in this project, on this machine (policy and maps are kept)."""
    from .project import pause

    root = _require_project()
    typer.echo(f"Paused in {root}. `pii-airlock on` resumes." if pause(root)
               else f"Already paused in {root}.")


@app.command()
def on() -> None:
    """Resume pii-airlock in this project."""
    from .project import resume

    root = _require_project()
    typer.echo(f"Guarding {root} again." if resume(root) else f"Already guarding {root}.")


@app.command()
def status() -> None:
    """Is this directory guarded, by which hooks, with which policy."""
    from . import hookinstall as hi
    from .project import config_path, find_project, is_paused, maps_dir

    config = _build_config(None, None)
    root = find_project()
    if root is not None and is_paused(root):
        state = f"PAUSED  {root}  (`pii-airlock on` resumes)"
    elif root is not None:
        state = f"on      {root}"
    elif config.activation == "always":
        state = "on      every directory (activation: always)"
    else:
        state = "off     not a guarded project (`pii-airlock init` guards it)"
    typer.echo(f"status   {state}")

    hooks = []
    if hi.claude_plugin_enabled():
        hooks.append("Claude Code plugin")
    for scope in ("user", "project"):
        if hi.claude_hook_installed(scope):
            hooks.append(f"Claude Code ({scope})")
        if hi.copilot_hook_installed(scope):
            hooks.append(f"Copilot ({scope})")
    typer.echo(f"hooks    {', '.join(hooks) or 'none (`pii-airlock init` installs them)'}")
    typer.echo(f"daemon   {_daemon_status(config)}")

    if root is not None:
        maps = list(maps_dir(root).glob("*.pii-map.json")) if maps_dir(root).is_dir() else []
        typer.echo(f"policy   {config_path(root)}")
        typer.echo(f"maps     {len(maps)} in {maps_dir(root)}")
    typer.echo(f"allow    {', '.join(config.allow_list) or '-'}")
    for entity, terms in config.deny_list.items() or {"": []}.items():
        typer.echo(f"deny     {entity + ': ' if entity else ''}{', '.join(terms) or '-'}")
    for pattern in config.custom_patterns:
        typer.echo(f"pattern  {pattern.get('entity')}  {pattern.get('regex')}")
    for entity, what in config.entity_actions.items():
        typer.echo(f"action   {entity}: {what}")
    typer.echo(f"decide   tools: {config.hook_decision}   prompts: {config.prompt_decision}   "
               f"on error: {config.hook_on_error}")
    if config.ignored_project_keys:
        typer.echo("NOT TRUSTED: this project's config came with the repo, so only settings that "
                   f"tighten protection apply (ignored: {', '.join(config.ignored_project_keys)}). "
                   "Review it, then run `pii-airlock trust`.")


@app.command()
def doctor() -> None:
    """Health checks for a local pii-airlock installation."""
    config = _build_config(None, None)
    if config.ner_backend == "gliner":
        models = [f"{config.gliner_model} (GLiNER)"]
        missing_models = ([] if importlib.util.find_spec("gliner")
                          else ["gliner package: pip install 'pii-airlock[gliner]'"])
    else:
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
        ("hook daemon", True, _daemon_status(config)),
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
    target: str = typer.Option("claude", "--target", help="claude | copilot"),
) -> None:
    """Register the Claude Code hook(s) in settings.json (or GitHub Copilot's hook file)."""
    from .hookinstall import install, install_copilot

    if target == "copilot":
        if scope not in ("project", "user"):
            typer.echo("--scope must be 'project' or 'user'", err=True)
            raise typer.Exit(code=1)
        path, changed = install_copilot(scope)
        if scope == "project":
            from .project import init_project

            init_project(Path.cwd())
        typer.echo(f"{'Installed' if changed else 'Already present:'} Copilot preToolUse hook "
                   f"in {path}. Prompts are not hookable in Copilot: route chat through the "
                   "gateway (see AGENTS.md).")
        return
    if target != "claude":
        typer.echo("--target must be 'claude' or 'copilot'", err=True)
        raise typer.Exit(code=1)
    try:
        path, added = install(event, scope)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None
    if scope == "project":
        from .project import init_project

        init_project(Path.cwd())  # a project hook is inert without the project home
    if added:
        typer.echo(f"Installed hooks {', '.join(added)} in {path}")
    else:
        typer.echo(f"Hooks already present in {path} — nothing to do.")


def _scope_path(scope: str) -> Path:
    from .config import USER_FILE
    from .project import config_path

    if scope == "user":
        return USER_FILE
    if scope != "project":
        typer.echo("--scope must be 'project' or 'user'", err=True)
        raise typer.Exit(code=1)
    return config_path(_require_project())


def _policy_change(fn, path: Path, *args) -> bool:
    """Run a policy edit; keep a trusted project trusted, never trust an unreviewed one."""
    from .policy import PolicyError
    from .project import HOME
    from .trust import is_trusted, trust

    project = path.parent.parent if path.parent.name == HOME else None
    was_trusted = project is not None and is_trusted(project)
    try:
        changed = fn(path, *args)
    except PolicyError as exc:
        typer.echo(f"{exc}\nFix the file by hand, then retry.", err=True)
        raise typer.Exit(code=1) from None
    if project is not None and was_trusted:
        trust(project)  # you just ran this: the file is yours
    elif project is not None:
        typer.echo("Note: this project's pii-airlock config came with the repo and is not "
                   "trusted, so settings that let more through are ignored. Review it, then "
                   "run `pii-airlock trust`.", err=True)
    return changed


@app.command()
def trust() -> None:
    """Trust this project's .pii-airlock/config.yaml as it is now.

    Project config can loosen protection (allow lists, `hook_on_error: open`...),
    so a project that came with a repo only gets its tightening settings applied
    until you have reviewed it and run this. Re-run it after config changes you
    pulled in.
    """
    from . import trust as trust_mod

    root = _require_project()
    trust_mod.trust(root)
    typer.echo(f"Trusted {root}/.pii-airlock/config.yaml")


@app.command()
def allow(
    term: str = typer.Argument(..., help="Term that is never PII here, e.g. your company."),
    scope: str = typer.Option("project", "--scope", help="project | user"),
) -> None:
    """Never treat TERM as PII (adds it to the policy allow list)."""
    from .policy import add_allow

    path = _scope_path(scope)
    if _policy_change(add_allow, path, term):
        typer.echo(f"Allowed {term!r} in {path}")
    else:
        typer.echo(f"{term!r} is already allowed in {path}")


@app.command()
def deny(
    term: str = typer.Argument(..., help="Term that is always sensitive, e.g. a client name."),
    entity: str = typer.Option("CONFIDENTIAL", "--as", help="Label used in tokens."),
    scope: str = typer.Option("project", "--scope", help="project | user"),
) -> None:
    """Always treat TERM as PII (adds it to the policy deny list)."""
    from .policy import add_deny

    path = _scope_path(scope)
    if _policy_change(add_deny, path, term, entity):
        typer.echo(f"Denied {term!r} (as {entity.upper()}) in {path}")
    else:
        typer.echo(f"{term!r} is already in the deny list of {path}")


@app.command()
def action(
    entity: str = typer.Argument(..., help="Entity type, e.g. IBAN_CODE, PERSON, SECRET."),
    what: str = typer.Argument(..., help="tokenize | redact | allow | block"),
    scope: str = typer.Option("project", "--scope", help="project | user"),
) -> None:
    """Choose what happens to an entity type: tokenize, redact, allow or block."""
    from .policy import set_action

    path = _scope_path(scope)
    if _policy_change(set_action, path, entity, what):
        typer.echo(f"{entity.upper()} -> {what.lower()} in {path}")
    else:
        typer.echo(f"{entity.upper()} is already {what.lower()} in {path}")


@hook_app.command("pre-tool-use")
def hook_pre_tool_use() -> None:
    """PreToolUse hook entry point (reads event JSON from stdin)."""
    from .hooks._common import run_pre_tool_use

    run_pre_tool_use()


@hook_app.command("user-prompt-submit")
def hook_user_prompt_submit() -> None:
    """UserPromptSubmit hook entry point (reads event JSON from stdin)."""
    from .hooks._common import run_user_prompt_submit

    run_user_prompt_submit()


@hook_app.command("session-start")
def hook_session_start() -> None:
    """SessionStart hook: tells Claude the project's PII rules when it is guarded."""
    from .hooks._common import run_session_start

    run_session_start()


def _daemon_status(config) -> str:
    from . import daemon

    if config.hook_daemon == "off":
        return "off (hook_daemon: off)"
    reply = daemon.call({"op": "ping"}, timeout=2.0)
    if reply is not None:
        return f"running (pid {reply.get('pid')}, {daemon.transport()} {daemon.endpoint()})"
    return "not running (starts on the next hook call)"


@daemon_app.command("start")
def daemon_start() -> None:
    """Start the daemon in the background and wait until it answers."""
    from . import daemon

    if daemon.call({"op": "ping"}, timeout=2.0) is None:
        daemon.spawn(str(Path.cwd()))
    reply = daemon.wait_until_up(10)
    if reply is None:
        typer.echo(f"Daemon did not start; see {daemon.log_path()}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"Daemon running (pid {reply.get('pid')}); models load in the background.")


@daemon_app.command("stop")
def daemon_stop() -> None:
    """Stop the running daemon."""
    from . import daemon

    reply = daemon.call({"op": "stop"}, timeout=2.0)
    typer.echo("Daemon stopped." if reply is not None else "No daemon running.")


@daemon_app.command("status")
def daemon_status() -> None:
    """Show whether the daemon is running."""
    typer.echo(_daemon_status(_build_config(None, None)))


@daemon_app.command("run")
def daemon_run() -> None:
    """Run the daemon in the foreground (for launchd/systemd or debugging)."""
    from . import daemon

    raise typer.Exit(code=daemon.serve(str(Path.cwd())))


if __name__ == "__main__":
    app()
