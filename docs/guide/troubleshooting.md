# Troubleshooting

Start with the health check. It names the problem most of the time.

```bash
pii-airlock doctor
```

Find your symptom below.

## Installing

### `command not found: pii-airlock` (or `pipx`)

The folder holding pipx programs is not on your path yet.

```bash
pipx ensurepath
```

Close the terminal and open a new one.

### `download-models` says my environment has no pip

Normal with pipx. The command prints lines like `pipx inject pii-airlock "<model-wheel-url>"`. Run them exactly as shown.

### `No module named spacy`

You ran a Python command in the wrong environment. Run `pii-airlock download-models` instead, from the same terminal
you use for the rest.

### `OSError: [E050] Can't find model …` after downloading

The model went into a different environment than the one pii-airlock runs in. Run the exact `pipx inject` command that
`download-models` prints.

### The gateway fails with `httpx`, `starlette` or `uvicorn` missing

```bash
pipx inject pii-airlock 'pii-airlock[proxy]'
```

### Word or PDF files are rejected

Install the extra: `pipx inject pii-airlock 'pii-airlock[docx]'` or `'pii-airlock[pdf]'`.

## Using the gateway

### My AI tool does not seem to use pii-airlock

- Is `pii-airlock proxy` still running in another terminal?
- Did you set the address **in the same terminal** you launched the tool from? Programs started from the Dock,
  Start menu or another window do not see it.
- Does the address end with the provider name (`/openai`, `/anthropic` or `/gemini`)?

### I get a 403 or 400 error

The gateway **refuses** requests it cannot clean safely: file uploads, audio, or a body that is not JSON.
Also, a type set to `block` triggers a 403 on purpose. The message names the type.

### The port is already in use

Another copy is probably running. Stop it, or choose another port: `pii-airlock proxy --port 8800`, and use that port in the address.

## Using hooks

### Everything is blocked after installing the Claude Code plugin

The plugin cannot find the `pii-airlock` command, and blocks everything by design. Install the program
([Install, all options](/guide/install)), then restart Claude Code.

### It flags things that are not personal

Teach it: `pii-airlock allow "the word"`. See [Tell it what is sensitive](/customize/allow-and-deny).
You can also raise the confidence threshold for a type, for example `score_thresholds: {PERSON: 0.7}`.

### Hooks are slow

The first call loads the models, which takes seconds. Later calls take about 60 ms.
Check the helper with `pii-airlock daemon status`.

### Every tool call is checked twice

You installed the hooks twice, for example the plugin and `install-hook`, or `install-hook` for Claude Code and for Copilot
in the same project. Keep one.

### A project's settings seem ignored

If the project came from someone else, only settings that tighten protection apply until you run `pii-airlock trust`
after reviewing the files. `pii-airlock policy show` lists what is being ignored.

## Developers

### `.venv/bin/pytest: bad interpreter`

Your virtualenv points at an old folder. Recreate it:

```bash
rm -rf .venv
python3 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e '.[dev]'
```

## Still stuck?

[Open a bug report](https://github.com/matinfo/pii-airlock/issues/new/choose) with:

- the output of `pii-airlock --version`
- how you installed it (pipx, Homebrew or pip)
- the exact command and the full error message

Never paste real personal data into a bug report.
