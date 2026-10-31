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
policy_app = typer.Typer(help="Per-project PII policy (Claude Code SKILL.md).",
                         no_args_is_help=True)
app.add_typer(policy_app, name="policy")


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
    return Path(f"{base}.pii-map.json")


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
        key = mapping_crypto.default_key() if encrypt_map else None
        mapping.save(target, encrypt_key=key)
        kind = "encrypted mapping" if encrypt_map else "Mapping"
        typer.echo(f"{kind} ({len(mapping)} entries) saved to {target}", err=True)


def _load_map(path: Path) -> Mapping:
    """Load a mapping file; an encrypted one is opened with this machine's key."""
    with path.open("rb") as fh:
        sealed = mapping_crypto.is_sealed(fh.read(len(mapping_crypto.MAGIC)))
    return Mapping.load(path, encrypt_key=mapping_crypto.default_key() if sealed else None)


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
    try:
        mapping = _load_map(map_path)
    except mapping_crypto.MappingDecryptError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None
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


def _scope_path(scope: str) -> Path:
    from .policy import skill_path

    if scope not in ("project", "user"):
        typer.echo("--scope must be 'project' or 'user'", err=True)
        raise typer.Exit(code=1)
    return skill_path(scope)


def _policy_change(fn, path: Path, *args) -> bool:
    """Run a policy edit; keep a trusted project trusted, never trust an unreviewed one."""
    from .policy import PolicyError, skill_path
    from .trust import is_trusted, trust

    project = Path.cwd()
    is_project = path == skill_path("project", project)
    was_trusted = is_project and is_trusted(project)
    try:
        changed = fn(path, *args)
    except PolicyError as exc:
        typer.echo(f"{exc}\nFix the policy block by hand, then retry.", err=True)
        raise typer.Exit(code=1) from None
    if is_project and was_trusted:
        trust(project)  # you just ran this: the files are yours
    elif is_project:
        typer.echo("Note: this project's pii-airlock config came with the repo and is not "
                   "trusted, so settings that let more through are ignored. Review it, then "
                   "run `pii-airlock trust`.", err=True)
    return changed


@policy_app.command("init")
def policy_init(
    scope: str = typer.Option("project", "--scope", help="project | user"),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing SKILL.md."),
) -> None:
    """Create the policy skill (.claude/skills/pii-airlock/SKILL.md)."""
    from .policy import init_skill

    path = _scope_path(scope)
    from .policy import skill_path
    from .trust import is_trusted, trust

    project = Path.cwd()
    was_trusted = path == skill_path("project", project) and is_trusted(project)
    if init_skill(path, force=force):
        if was_trusted:
            trust(project)
        typer.echo(f"Created {path}")
        typer.echo("Next: pii-airlock allow \"Your Company\"  /  pii-airlock deny \"Client X\"")
    else:
        typer.echo(f"{path} already exists — nothing to do (use --force to overwrite).")


@app.command()
def trust() -> None:
    """Trust this project's .pii-airlock.yaml and SKILL.md policy as they are now.

    Project config can loosen protection (allow lists, `hook_on_error: open`...),
    so a project that came with a repo only gets its tightening settings applied
    until you have reviewed it and run this. Re-run it after config changes you
    pulled in.
    """
    from . import trust as trust_mod

    project = Path.cwd()
    if not trust_mod.has_project_config(project):
        typer.echo("No project config here — nothing to trust.")
        return
    trust_mod.trust(project)
    typer.echo(f"Trusted the pii-airlock config of {project}")


@policy_app.command("show")
def policy_show() -> None:
    """Show the effective policy for the current project and where it comes from."""
    from .policy import skill_path

    config = _build_config(None, None)
    for scope in ("user", "project"):
        path = skill_path(scope)
        typer.echo(f"{scope:<8} {path}  {'(found)' if path.is_file() else '(none)'}")
    typer.echo(f"allow_list:      {', '.join(config.allow_list) or '-'}")
    for entity, terms in config.deny_list.items():
        typer.echo(f"deny_list {entity}: {', '.join(terms)}")
    if not config.deny_list:
        typer.echo("deny_list:       -")
    for pattern in config.custom_patterns:
        typer.echo(f"custom pattern:  {pattern.get('entity')}  {pattern.get('regex')}")
    for entity, what in config.entity_actions.items():
        typer.echo(f"action {entity}: {what}")
    if config.ignored_project_keys:
        typer.echo("NOT TRUSTED project config: only settings that tighten protection apply; "
                   f"ignored: {', '.join(config.ignored_project_keys)}. "
                   "Review it, then run `pii-airlock trust`.")
    typer.echo(f"hook_decision: {config.hook_decision}   prompt_decision: "
               f"{config.prompt_decision}   hook_on_error: {config.hook_on_error}")


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


def _daemon_status(config) -> str:
    from . import daemon

    if not daemon.SUPPORTED:
        return "unsupported on this OS (hooks analyze in-process)"
    if config.hook_daemon == "off":
        return "off (hook_daemon: off)"
    reply = daemon.call({"op": "ping"}, timeout=2.0)
    if reply is not None:
        return f"running (pid {reply.get('pid')}, socket {daemon.socket_path()})"
    return "not running (starts on the next hook call)"


@daemon_app.command("start")
def daemon_start() -> None:
    """Start the daemon in the background and wait until it answers."""
    from . import daemon

    if not daemon.SUPPORTED:
        typer.echo("The hook daemon needs Unix sockets (not available here).", err=True)
        raise typer.Exit(code=1)
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
