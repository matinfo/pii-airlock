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
John Smith (john@acme.com) → <PERSON_482913> (<EMAIL_ADDRESS_093117>)
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

On macOS or Linux with [Homebrew](https://brew.sh/) (installs the CLI, hooks and gateway
in their own virtualenv; the optional `gliner`, `docx` and `pdf` extras need pipx):

```bash
brew install matinfo/tap/pii-airlock
pii-airlock download-models         # spaCy models, downloaded once
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

### Quick verification

```bash
echo "Contact John Smith at john@example.com" \
  | pii-airlock scrub --map /tmp/test.pii-map.json -o /tmp/scrubbed.txt
cat /tmp/scrubbed.txt   # Contact <PERSON_482913> at <EMAIL_ADDRESS_093117>
pii-airlock restore /tmp/scrubbed.txt --map /tmp/test.pii-map.json
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
- A **fresh in-memory mapping per request** — the gateway writes no PII to disk (only
  the stable-token key, see [Tokens](#tokens)).
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
# → Contacte <PERSON_558644> à <EMAIL_ADDRESS_094087>

# 2. Send the scrubbed text to your LLM …

# 3. Restore — swap tokens back in the model's response (use your own tokens)
echo "J'ai répondu à <PERSON_558644> via <EMAIL_ADDRESS_094087>." \
  | pii-airlock restore --map /tmp/m.pii-map.json
# → J'ai répondu à Jean Dupont via jean@acme.fr.
```

### Tokens

Same value, same token, so the model still sees coreference. By default tokens are
**stable**: `<PERSON_558644>` is a keyed hash (HMAC-SHA256) of the value, so it is the
same in every request, file and process — across turns, subagents, trimmed or compacted
histories — and prompt caches keep hitting. The key is created on first use in
`~/.local/state/pii-airlock/token.key` (owner-only) and never leaves your machine;
without it a token reveals nothing about its value.

- `token_rotation: day` (default) | `week` | `never` — how long a value keeps its
  token. Tokens cannot be linked across periods, so a provider cannot follow one person
  through all your conversations. Use `never` to scrub a dataset in several runs.
- `token_style: surrogate` — realistic fakes instead of tokens, keyed the same way:
  `Jean Dupont` → `Jasper Iverson`, `jean.dupont@acme.fr` → `jasper.iverson@example.com`;
  phones, cards (Luhn-valid), IBANs (valid checksum) keep their shape, IPs come from the
  documentation ranges. Text reads naturally, which some models and tools handle better
  than `<TOKENS>`. A surname alone gets the surname of the full fake, and restores alone
  too. Other entities (IDs, secrets, places) keep stable tokens. Trade-off: a fake the
  model writes in another sense (a fake first name alone, for someone else) is restored
  as well.
- `token_style: sequential` — `<PERSON_1>`, `<PERSON_2>` in reading order, per request
  or file (the previous default).
- Delete `token.key` to rotate the key immediately.

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

**Speed: the hook daemon.** Claude Code starts a new process for every hook call, and
loading the spaCy models costs 0.5–3 s each time. With the default `hook_daemon: auto`,
the first hook call starts a small background daemon that keeps the models loaded;
later calls answer in ~60 ms. It listens on a Unix socket (mode 0600, in a directory
only you can write to), reloads your project policy on every call, and exits after
`hook_daemon_idle_minutes` (30) idle. Nothing leaves your machine.

```bash
pii-airlock daemon status     # also shown by `pii-airlock doctor`
pii-airlock daemon start      # warm it up now (e.g. from your shell profile)
pii-airlock daemon stop
```

While no daemon answers, hooks analyze in-process (`hook_fallback: inprocess`). With
`hook_fallback: regex` they use patterns only, in milliseconds: emails, phones, IBANs,
cards, IPs, FR/CH IDs, secrets and your `deny_list` — **names and places are not
detected** in that mode. `hook_daemon: off` disables the daemon. Windows: no daemon
(hooks analyze in-process).

**Not covered by hooks:** the *output* of a command or tool (e.g. `cat` in Bash, Grep
matches, a fetched web page) reaches the model unchecked, as do binary files (images,
PDFs). For full coverage, route the traffic through the gateway.

---

## Configuration

Override chain (lowest → highest priority):

```
bundled defaults → ~/.config/pii-airlock/config.yaml → ~/.claude/skills/pii-airlock/SKILL.md
  → ./.pii-airlock.yaml → ./.claude/skills/pii-airlock/SKILL.md → CLI flags
```

`allow_list`, `deny_list` and `custom_patterns` accumulate across layers (your
personal allow list + the project's); every other key is overridden.

Default config (`config.default.yaml`):

```yaml
languages: [en, fr]
models:
  en: en_core_web_lg
  fr: fr_core_news_lg
score_threshold: 0.5
entities: []          # empty = all entities Presidio recognizes, minus exclude_entities
entity_actions: {}    # per type: tokenize | redact | allow | block (see Per-project policy)
exclude_entities: [DATE_TIME, URL, NRP, US_DRIVER_LICENSE, US_BANK_NUMBER,
                   US_PASSPORT, IN_VEHICLE_REGISTRATION]  # noisy in code; [] keeps all
score_thresholds: {}  # per-entity minimum, e.g. {PERSON: 0.7}
builtin_recognizers: true  # FR/CH IDs, FR/CH phone formats, secrets (see below)
analysis_cache_size: 2048  # texts remembered per language (digest + offsets, never the text); 0 = off
hook_daemon: auto          # keep models loaded between hook calls (off: never)
hook_fallback: inprocess   # no daemon answer: load models (inprocess) or patterns only (regex)
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

Mapping files hold the real values, so the file backend **encrypts them at rest**
(AES-256-GCM, key derived from `token.key` in the state directory). A copied or
backed-up `maps/` directory is then useless without that key: keep `token.key` out of
backups, and note that losing it makes pending mappings unreadable (they only live for
one request). Plain files from older versions still load. Set `mapping_encryption: false`
to write readable JSON for debugging; this is ignored in an untrusted project's config.
Files from `pii-airlock scrub --map` stay plain JSON, as you restore them by hand.

### Built-in recognizers

On top of Presidio, pii-airlock ships checksum-validated recognizers that work in
every language and need no model:

| Entity | What | Validation |
|---|---|---|
| `FR_NIR` | French social security number | mod-97 key (incl. Corsica 2A/2B) |
| `CH_AHV` | Swiss AHV/AVS number `756.xxxx.xxxx.xx` | EAN-13 check digit |
| `FR_SIRET` / `FR_SIREN` | French business IDs (sole traders are people) | Luhn; SIREN needs the keyword |
| `DE_TAX_ID` | German tax ID (Steuer-IdNr.), needs the keyword (`Steuer-ID`, `IdNr`) | ISO 7064 MOD 11,10 |
| `DE_TAX_NUMBER` | German `Steuernummer` (`21/815/08150`), needs the keyword | format |
| `IT_VAT_CODE` | Italian Partita IVA, with the `IT` prefix or a `P.IVA` keyword | Luhn |
| `PHONE_NUMBER` | International `+CC …` in any language; FR/CH/DE/IT national formats (`06 12 34 56 78`, `079 123 45 67`, `030 12345678`, `333 1234567`) | format |
| `SECRET` | AWS/GitHub/Slack/OpenAI/Anthropic/Google/Stripe keys, JWTs, private keys, URL passwords, `password=…` values | format |

Exclude any of them with `exclude_entities`, or all with `builtin_recognizers: false`.

### Per-project policy (Claude Code skill)

The project policy lives in `.claude/skills/pii-airlock/SKILL.md`. Claude Code loads
it as a skill (rules for handling personal data, what to do when a hook blocks), and
pii-airlock reads its fenced `yaml pii-airlock` block as config.

```bash
pii-airlock policy init                  # create the skill for this project
pii-airlock allow "Acme SA"              # never PII here (your company, products)
pii-airlock deny "Project Phoenix" --as CODENAME   # always sensitive here
pii-airlock allow "Jane Roe" --scope user          # personal, all projects
pii-airlock policy show                  # effective policy and where it comes from
```

```yaml pii-airlock
allow_list: [Acme SA]
deny_list:
  CODENAME: [Project Phoenix]
custom_patterns:
  - {entity: CONTRACT_ID, regex: 'CT-\d{6}'}
```

Hooks apply the policy of the project Claude Code is working in. Every detection
message shows the one-command fix for a false positive.

**Trust.** A project's policy comes with the repo, and a policy can loosen protection
(`allow_list`, `hook_on_error: open`, `entity_actions: {PERSON: allow}`...). So for a
project you have not trusted, only settings that **tighten** apply (deny-list terms,
custom patterns, `block` / `redact`, `deny` / `block` / `closed` decisions). Your own
`allow`, `deny`, `action` and `policy init` edits keep a trusted project trusted; after
a `git pull` that changes the policy, review it and run `pii-airlock trust`.
`pii-airlock policy show` says what is being ignored. User-level config is always trusted.

#### What happens to each entity type

By default every detected entity is **tokenized** (reversible). Choose per type:

| Action | Effect |
|---|---|
| `tokenize` | token or fake, restored in the response (default) |
| `redact` | irreversible `[IBAN_CODE]`; the value is never kept, not even in a mapping file |
| `allow` | left as is and not flagged (what `exclude_entities` does for its list) |
| `block` | the gateway answers **403** and sends nothing, `scrub` writes nothing, hooks **deny** (even with `hook_decision: ask`) and block prompts (even with `prompt_decision: warn`); messages name the type and count, never the value |

```bash
pii-airlock action IBAN_CODE redact          # this project
pii-airlock action CREDIT_CARD block --scope user
```

```yaml pii-airlock
entity_actions:
  IBAN_CODE: redact
  SECRET: block        # API keys and passwords never leave the machine
  LOCATION: allow
```

Layers accumulate (user policy + project policy); an explicit action beats
`exclude_entities`. Names found elsewhere in the text keep following their person:
with `EMAIL_ADDRESS: allow`, `marie@acme.fr` stays but a bare `marie` that
matches a detected "Marie Dubois" is still tokenized.

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

### One multilingual model (GLiNER)

Instead of a spaCy model per language, [GLiNER](https://github.com/urchade/GLiNER)
(`urchade/gliner_multi_pii-v1`) finds people, organizations and places in any language
with one model. Emails, phones, IDs and secrets are still found by patterns.

```bash
pipx inject pii-airlock 'pii-airlock[gliner]'   # or: pip install 'pii-airlock[gliner]' (PyTorch)
pii-airlock download-models                     # with ner_backend: gliner, fetches the ~1.1 GB model
```

```yaml
ner_backend: gliner
```

On the bundled EN+FR eval corpus (`python -m tests.eval.run_eval --backend gliner`):

| | spaCy `_sm` models | GLiNER |
|---|---|---|
| PERSON recall / precision | 0.96 / 0.68 | 1.00 / 0.95 |
| All entities, precision | 0.67 | 0.98 |
| Time per message (CPU) | ~6 ms | ~40 ms |

Fewer false positives means fewer needless hook prompts. Long texts are scanned in
overlapping windows (GLiNER itself truncates past a few hundred words). Organizations
and places must be capitalized to count, which drops common nouns GLiNER tags ("la
société", "client"); names are kept in any case. With the hook daemon the model is
loaded once.

---

## Guarantees & limitations

**What pii-airlock guarantees**

- **Reversibility is exact.** Any value the engine tokenized is restored byte-for-byte
  via the mapping. `restore(scrub(text))` round-trips for tokenized spans.
- **Determinism.** The same value gets the same token within a mapping (and, with stable
  tokens, across requests), so coreference is preserved for the model.
- **Found once, scrubbed everywhere.** A value detected anywhere in a request or file
  — and the parts of a person's name — is scrubbed at every other mention, earlier ones
  included, even where the model missed it.
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
- `scrub --encrypt-map` writes the file encrypted (AES-256-GCM, key derived from
  `token.key` in your state directory); `restore --map` opens it with the same key
  automatically. Opt-in because such a file is only restorable on this machine, and
  only while `token.key` exists: keep `token.key` out of backups, never in the repo.
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

Unit tests stub out Presidio/spaCy and run entirely offline. Detection quality is measured separately on a labeled EN+FR+DE+IT corpus (fake data) with the real small models: `python -m tests.eval.run_eval -v` prints per-entity recall/precision, `--gate` fails below `tests/eval/thresholds.json` (also `pytest -m eval`). Add a case to `tests/eval/corpus.jsonl` when you fix a miss.

 For a live end-to-end check, run `pii-airlock download-models` first, then:

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
