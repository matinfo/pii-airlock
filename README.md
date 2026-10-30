# pii-airlock

> **Keep real personal data out of AI prompts in minutes — local, reversible, and provider-agnostic.**

[![CI](https://github.com/matinfo/pii-airlock/actions/workflows/ci.yml/badge.svg)](https://github.com/matinfo/pii-airlock/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/pii-airlock.svg)](https://pypi.org/project/pii-airlock/)
![Python](https://img.shields.io/badge/python-3.10%E2%80%933.14-blue.svg)
![Platforms](https://img.shields.io/badge/platforms-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey.svg)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

**[2-min quickstart](#2-minute-quickstart) · [Install](#install) · [Gateway](#universal-gateway-any-provider) · [CLI](#cli-usage) · [doctor](#doctor-health-checks) · [Troubleshooting](#troubleshooting) · [All agents →](AGENTS.md)**

`pii-airlock` is a local privacy layer for AI tools. It replaces personal data with placeholders before requests leave your machine, then restores originals in responses.

Example:

```text
John Smith (john@acme.com) → <PERSON_1> (<EMAIL_ADDRESS_1>)
```

Runs on **macOS, Linux, Windows** (Python ≥ 3.10). Built on [Microsoft Presidio](https://microsoft.github.io/presidio/).

---

## Why people use pii-airlock

| Problem | What pii-airlock gives you |
|---|---|
| You use multiple AI clients/providers | One local gateway URL for all of them |
| You need reversible anonymization | Stable placeholders + local mapping file |
| You use Claude Code tools/files | Native hooks for prompt + tool-data checks |
| You want to avoid vendor lock-in | Provider adapters: OpenAI-style, Anthropic, Gemini |

Detection happens locally. Gateway traffic is forwarded only after PII is replaced.

---

## 2-minute quickstart

If you just want the safest default for most users:

```bash
pipx install "pii-airlock[proxy]"
pii-airlock init
pii-airlock proxy
```

Then set your client base URL:

```bash
export OPENAI_BASE_URL=http://127.0.0.1:8745/openai
```

PowerShell:

```powershell
$env:OPENAI_BASE_URL = "http://127.0.0.1:8745/openai"
```

Now prompts are scrubbed before provider calls, and responses are restored automatically.

---

## Install

Requires Python ≥ 3.10 and [pipx](https://pipx.pypa.io/) (recommended) or pip.
Works the same on macOS, Linux and Windows.

```bash
pipx install "pii-airlock[proxy]"   # recommended (gateway included)
pii-airlock init                    # guided setup (models + env hints)
```

Latest from source (before a release lands on PyPI):

```bash
pipx install git+https://github.com/matinfo/pii-airlock
```

Optional format support (plain text, CSV and JSON work out of the box):

```bash
pipx inject pii-airlock 'pii-airlock[docx]'   # Word .docx
pipx inject pii-airlock 'pii-airlock[pdf]'    # PDF (text extraction)
pipx inject pii-airlock 'pii-airlock[all]'    # everything
```

If you installed without gateway support and need it later:

```bash
pipx inject pii-airlock 'pii-airlock[proxy]'
```

If `download-models` reports that your interpreter has no `pip` (common in
`pipx`), run the printed `pipx inject pii-airlock "<model-wheel-url>"` commands.
The command now prints exact model wheel URLs for you.

### doctor health checks

```bash
pii-airlock doctor
```

This checks proxy dependencies, model installation, and mapping roundtrip in one command.

### Quick verification (2 commands)

```bash
echo "Contact John Smith at john@example.com" | pii-airlock scrub --map /tmp/test.pii-map.json
echo "Replied to <PERSON_1> on <EMAIL_ADDRESS_1>." | pii-airlock restore --map /tmp/test.pii-map.json
```

---

## Universal gateway (any provider)

The gateway is the easiest mode for non-technical users: point your AI client at
`localhost`, and pii-airlock handles scrub/restore automatically.

```
  your app ──http──▶ pii-airlock gateway ──https──▶ provider API
           ◀───────────  (restore)  ◀───────────  (scrub)
```

```bash
# already included if you installed with "pii-airlock[proxy]"
# pipx inject pii-airlock 'pii-airlock[proxy]'
pii-airlock proxy            # listens on http://127.0.0.1:8745
```

Then set the base URL in whatever client you use:

```bash
# OpenAI SDK / Codex CLI / most OpenAI-compatible tools
export OPENAI_BASE_URL=http://127.0.0.1:8745/openai

# Anthropic SDK
export ANTHROPIC_BASE_URL=http://127.0.0.1:8745/anthropic

# Google Gemini — use base path
#   https://generativelanguage.googleapis.com  ->  http://127.0.0.1:8745/gemini
```

**Why this is practical:** configure once, keep existing clients, and avoid changing prompt habits.

- **No TLS interception.** Your client talks plain HTTP to `localhost`; the proxy makes
  the real HTTPS call upstream. No certificates to install. Bind stays on `127.0.0.1` by default.
- **Auth passes through** untouched and pii-airlock never logs request headers or bodies.
  (uvicorn runs at log level `warning`, so request lines aren't logged either.)
- A **fresh in-memory mapping per request** — the gateway writes nothing to disk.
- **Concurrency-safe:** detection is serialized with a lock, so the engine is shared
  safely across simultaneous requests.

**Provider coverage** — three wire formats, each with an adapter in `pii_scrub/payload.py`:

| Route | Wire format | Covers | Streaming |
|---|---|---|---|
| `/openai` | Chat Completions, Responses, Completions, Embeddings, Moderations | OpenAI, Codex, Cursor, Continue, Ollama, LiteLLM, vLLM, … | SSE ✅ |
| `/anthropic` | Messages (incl. `count_tokens`, batches) | Claude SDKs, Claude-compatible tools | SSE ✅ |
| `/gemini` | generateContent, countTokens, embedContent | Google Gemini | SSE ✅ · array-stream buffered |

Tool traffic is covered too: tool results / function outputs (where file contents
and command output live) and tool-call arguments are scrubbed on the way out;
tool-call arguments the model emits are restored on the way back.

**Fail closed.** A request body the gateway doesn't know how to scrub — an unknown
endpoint (file uploads, audio, …) or a body that isn't JSON — is refused (403/400)
instead of being forwarded. Opt specific paths out with `passthrough_paths` if you
know they carry no personal data.

Need setup for a specific client? Use **[AGENTS.md](AGENTS.md)** (Claude Code, Codex, Cursor, Continue, Aider, Gemini).

---

## CLI usage

### Reversible scrub → restore pipe

```bash
# 1. Scrub — replaces PII with tokens, saves a mapping file
echo "Contacte Jean Dupont à jean@acme.fr" \
  | pii-airlock scrub --map /tmp/m.pii-map.json
# → Contacte <PERSON_1> à <EMAIL_ADDRESS_1>

# 2. Send the scrubbed text to your LLM …

# 3. Restore — swap tokens back in the model's response
echo "J'ai répondu à <PERSON_1> via <EMAIL_ADDRESS_1>." \
  | pii-airlock restore --map /tmp/m.pii-map.json
# → J'ai répondu à Jean Dupont via jean@acme.fr.
```

Same value always gets the same token (`<PERSON_1>`) so the model still sees coreference.

### Detect without changing text

```bash
pii-airlock detect notes.txt
# PERSON           0.85  [9:21]    'Jean Dupont'
# EMAIL_ADDRESS    0.99  [24:38]   'jean@acme.fr'
```

### File formats

```bash
pii-airlock scrub report.csv  -o report.scrubbed.csv
pii-airlock scrub data.json   -o data.scrubbed.json
pii-airlock scrub contract.docx -o contract.scrubbed.docx   # requires [docx]
pii-airlock scrub scan.pdf                                   # requires [pdf] → text on stdout
```

### Other options

```bash
pii-airlock scrub prompt.txt --no-map          # irreversible one-way scrub
pii-airlock scrub --lang fr,en                 # explicit language list
pii-airlock scrub --threshold 0.7              # raise confidence cutoff
pii-airlock scrub input.txt -o out.txt --map secrets.pii-map.json
```

---

## Claude Code hooks

Register guardrails that intercept PII before it reaches the model:

```bash
pii-airlock install-hook                  # both events, project .claude/settings.json
pii-airlock install-hook --scope user     # ~/.claude/settings.json (all projects)
pii-airlock install-hook --event tool     # PreToolUse only
pii-airlock install-hook --event prompt   # UserPromptSubmit only
```

| Leak vector | Covered by | Default action |
|---|---|---|
| PII you type in a prompt | `UserPromptSubmit` | **block**, shows a scrubbed version to send instead |
| PII in a text file Claude reads (the hook scans the file content) | `PreToolUse` (`Read`) | ask |
| PII in a shell command, file write/edit, search pattern, URL or web query | `PreToolUse` | ask |
| PII in MCP tool arguments | `PreToolUse` (`mcp__*`) | ask |

The hooks **detect and block/ask** — they don't silently rewrite payloads (the hook API doesn't support in-place rewriting). For a silent, reversible rewrite, use the CLI pipe above.

- `hook_decision: deny` blocks tool calls instead of asking.
- `prompt_decision: warn` sends prompts containing PII anyway, with a warning
  (Claude Code has no "ask" for prompts: it's block or send).
- If detection can't run (e.g. missing spaCy model), the hooks **fail closed**: the
  input is treated as containing PII. Set `hook_on_error: open` to skip checks instead.

**Not covered by hooks:** the *output* of a command or tool (e.g. `cat` in Bash, Grep
matches, a fetched web page) reaches the model unchecked, as do binary files (images,
PDFs). For full coverage, route the traffic through the gateway.

---

## Configuration

Override chain (lowest → highest priority):

```
bundled defaults → ~/.config/pii-airlock/config.yaml → ./.pii-airlock.yaml → CLI flags
```

Default config (`config.default.yaml`):

```yaml
languages: [en, fr]
models:
  en: en_core_web_lg
  fr: fr_core_news_lg
score_threshold: 0.5
entities: []          # empty = all entities Presidio recognizes
hook_decision: ask    # tool calls: ask (surface + confirm) | deny (block)
prompt_decision: block  # prompts: block (show scrubbed version) | warn (send anyway)
hook_on_error: closed   # detection failure: closed (treat as PII) | open (skip)
hook_max_file_bytes: 2000000  # larger files read by Claude count as a detection failure
passthrough_paths: []   # gateway: path fragments whose bodies may be forwarded unscrubbed

# Advanced (proxy runtime):
mapping_backend: memory   # memory (default) | file
# mapping_dir: /var/lib/pii-airlock/maps
```

For higher-volume/self-hosted setups, `mapping_backend: file` can be useful for
debugging or operational inspection. `memory` stays the safest default for local
use because mappings are ephemeral.

### Adding a language

```bash
python -m spacy download de_core_news_lg
```

```yaml
# .pii-airlock.yaml
languages: [en, fr, de]
models:
  de: de_core_news_lg
```

---

## Guarantees & limitations

**What pii-airlock guarantees**

- **Reversibility is exact.** Any value the engine tokenized is restored byte-for-byte
  via the mapping. `restore(scrub(text))` round-trips for tokenized spans.
- **Determinism.** The same value gets the same token within a mapping, so coreference
  is preserved for the model.
- **Tokens are opaque & safe.** Restored values are re-inserted through proper JSON
  encoding; values containing quotes, newlines or `<…>` won't corrupt payloads.
- **Local-only detection.** Detection never makes a network call. Only the gateway
  forwards (already-scrubbed) traffic onward.

**What it does *not* guarantee — read this**

- **Detection is best-effort, not complete.** Presidio + spaCy are statistical; they
  miss and mis-tag entities (more so with `_sm` models, or for phone numbers with odd
  spacing). pii-airlock reduces exposure — it is **not** a guarantee that every piece of
  PII is removed. Review sensitive material; raise `score_threshold` or add custom
  recognizers as needed.
- **Gateway scope.** Text in generation, embedding and token-count requests is scrubbed,
  including tool results and tool-call arguments. Images, audio and file attachments
  inside a request are forwarded as-is (not inspected). Other endpoints with a body are
  refused unless listed in `passthrough_paths`. Anthropic `thinking` blocks are signed,
  so they are neither scrubbed nor restored.
- **All configured languages are analyzed** for every text and the results merged, so
  mixed EN/FR text is covered — at the cost of one NER pass per language.
- **Gemini array streaming** (without `alt=sse`) is buffered, then restored as one
  response rather than streamed live.
- **`.docx`** scrubbing rewrites changed paragraphs into a single run, so inline
  formatting within those paragraphs is not preserved. **PDF** is extract-only → scrubbed
  text out (no PDF re-render).

---

## Platform support

Tested in CI on **Linux, macOS and Windows** (Python 3.10–3.14 on Linux; 3.12–3.13 on
macOS/Windows). One platform nuance:

- Mapping files are created with mode **`0600` on POSIX** (macOS/Linux). **On Windows**
  `chmod` is a no-op; the file inherits your account's default ACLs — typically already
  user-private in a home directory. Treat mapping files as secrets regardless (below).

---

## Troubleshooting

Run this first for a quick diagnosis:

```bash
pii-airlock doctor
```

**`.venv/bin/pytest: bad interpreter .../pii-scrub/...`**

Your venv points to an old repo path. Recreate it:

```bash
rm -rf .venv
python3 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e '.[dev]'
```

**`No module named spacy` when running `python -m spacy ...`**

You are likely using system Python instead of the `pii-airlock` environment.
Use:

```bash
pii-airlock download-models
```

**`download-models` says this interpreter has no pip**

This is normal in many `pipx` environments. Run the exact `pipx inject` command
printed by `download-models` for each model wheel URL.

**`pii-airlock proxy` fails with missing `httpx` / `starlette` / `uvicorn`**

Install gateway dependencies:

```bash
pipx inject pii-airlock 'pii-airlock[proxy]'
```

**`OSError: [E050] Can't find model ...` after download**

Install the model wheel directly into the same environment where `pii-airlock`
runs (the command prints the exact wheel URL in this case).

---

## ⚠ Security: the mapping file holds real PII

`*.pii-map.json` contains the **original personal data** in plain text.

- Created owner-only (`0600` on POSIX; default user ACLs on Windows — see above).
- The bundled `.gitignore` excludes `*.pii-map.json` and `*.pii-map.*`.
- **Never commit mapping files.**
- Delete them when you no longer need to restore.
- Use `--no-map` when reversibility isn't required.
- The gateway keeps its mapping in memory only and discards it after each response.

---

## Development

```bash
git clone https://github.com/matinfo/pii-airlock
cd pii-airlock
pip install -e ".[dev]"
ruff check .
pytest -q
```

Unit tests stub out Presidio/spaCy and run entirely offline. For a live end-to-end check, run `pii-airlock download-models` first, then:

```bash
echo "Call John Smith at john@example.com" | pii-airlock scrub --map /tmp/test.pii-map.json
```

---

## Community

- 🧩 **[Integrate with your agent](AGENTS.md)** — Claude Code, Cursor, Codex, Gemini, Continue, Aider, …
- ❓ **Need help?** Open a **[bug report](https://github.com/matinfo/pii-airlock/issues/new/choose)** with:
  - `pii-airlock --version`
  - your install method (`pipx` or `pip`)
  - the exact command and full error output
- 🤝 **[Contributing](CONTRIBUTING.md)** — adding a language or a provider adapter is a great first PR
- 🔒 **[Security policy](SECURITY.md)** — responsible disclosure + the honest threat model
- 📜 **[Changelog](CHANGELOG.md)** · **[Code of Conduct](CODE_OF_CONDUCT.md)**

If pii-airlock helps you keep PII out of your AI tools, a ⭐ helps others find it.

---

## License

[MIT](LICENSE) © pii-airlock contributors
