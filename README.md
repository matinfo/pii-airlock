# pii-scrub

Local, **reversible** PII anonymizer built on [Microsoft Presidio](https://microsoft.github.io/presidio/).  
Keep real personal data off LLM round-trips — replace it with stable placeholder tokens, send the scrubbed text to the model, then swap the originals back in from a local mapping file.

Everything runs **100% locally**. No data ever leaves your machine.

---

## Three workflows

| Workflow | What it does | Works with |
|---|---|---|
| **Gateway** (proxy) | Transparent scrub-out / restore-in on the wire | OpenAI, Codex, Anthropic, Gemini, Cursor, Continue, … |
| **CLI pipe** | `pii-scrub scrub` → LLM → `pii-scrub restore` — reversible, scriptable | anything |
| **Claude Code hooks** | Detect PII before it reaches the model, on prompts *and* tool data | Claude Code |

All three share one detection engine — provider knowledge lives only in small payload adapters.

---

## Install

Requires Python ≥ 3.10 and [pipx](https://pipx.pypa.io/) (recommended) or pip.

```bash
pipx install git+https://github.com/matinfo/pii-scrub
# or: pip install git+https://github.com/matinfo/pii-scrub

# Download the NLP models (en + fr by default)
pii-scrub download-models
```

Optional format support (plain text, CSV and JSON work out of the box):

```bash
pipx inject pii-scrub 'pii-scrub[proxy]'  # universal gateway (any provider)
pipx inject pii-scrub 'pii-scrub[docx]'   # Word .docx
pipx inject pii-scrub 'pii-scrub[pdf]'    # PDF (text extraction)
pipx inject pii-scrub 'pii-scrub[all]'    # everything
```

---

## Universal gateway (any provider)

The gateway is a **local reverse proxy**. Point any LLM client at it via the client's
base-URL setting; the proxy scrubs PII out of outbound requests and restores the real
values in the responses — including streamed ones. The client never sees the difference.

```
  your app ──http──▶ pii-scrub gateway ──https──▶ provider API
           ◀───────────  (restore)  ◀───────────  (scrub)
```

```bash
pipx inject pii-scrub 'pii-scrub[proxy]'
pii-scrub proxy            # listens on http://127.0.0.1:8745
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

**Why a proxy?** It's the only interception point that is simultaneously transparent
(configure once), bidirectional (scrubs the prompt *and* restores the answer
automatically), universal (every provider speaks HTTP), and enforceable (a client that
only knows the proxy URL can't leak around it).

- **No TLS interception.** Your client talks plain HTTP to `localhost`; the proxy makes
  the real HTTPS call upstream. No certificates to install.
- **Auth passes through** untouched and is **never logged**.
- A **fresh in-memory mapping per request** — nothing is written to disk.

> Adding a provider = one small payload adapter (`pii_scrub/payload.py`): the three
> built-in wire formats (OpenAI-compatible, Anthropic, Gemini) already cover most tools.
> Gemini's non-SSE streaming is buffered then restored (one response instead of a live stream).

---

## CLI usage

### Reversible scrub → restore pipe

```bash
# 1. Scrub — replaces PII with tokens, saves a mapping file
echo "Contacte Jean Dupont à jean@acme.fr" \
  | pii-scrub scrub --map /tmp/m.pii-map.json
# → Contacte <PERSON_1> à <EMAIL_ADDRESS_1>

# 2. Send the scrubbed text to your LLM …

# 3. Restore — swap tokens back in the model's response
echo "J'ai répondu à <PERSON_1> via <EMAIL_ADDRESS_1>." \
  | pii-scrub restore --map /tmp/m.pii-map.json
# → J'ai répondu à Jean Dupont via jean@acme.fr.
```

Same value always gets the same token (`<PERSON_1>`) so the model still sees coreference.

### Detect without changing text

```bash
pii-scrub detect notes.txt
# PERSON           0.85  [9:21]    'Jean Dupont'
# EMAIL_ADDRESS    0.99  [24:38]   'jean@acme.fr'
```

### File formats

```bash
pii-scrub scrub report.csv  -o report.scrubbed.csv
pii-scrub scrub data.json   -o data.scrubbed.json
pii-scrub scrub contract.docx -o contract.scrubbed.docx   # requires [docx]
pii-scrub scrub scan.pdf                                   # requires [pdf] → text on stdout
```

### Other options

```bash
pii-scrub scrub prompt.txt --no-map          # irreversible one-way scrub
pii-scrub scrub --lang fr,en                 # explicit language list
pii-scrub scrub --threshold 0.7              # raise confidence cutoff
pii-scrub scrub input.txt -o out.txt --map secrets.pii-map.json
```

---

## Claude Code hooks

Register guardrails that intercept PII before it reaches the model:

```bash
pii-scrub install-hook                  # both events, project .claude/settings.json
pii-scrub install-hook --scope user     # ~/.claude/settings.json (all projects)
pii-scrub install-hook --event tool     # PreToolUse only
pii-scrub install-hook --event prompt   # UserPromptSubmit only
```

| Leak vector | Covered by |
|---|---|
| PII you type in a prompt | `UserPromptSubmit` |
| PII in a file Claude reads | `PreToolUse` |
| PII in a shell command Claude runs | `PreToolUse` |

The hooks **detect and warn/ask** — they don't silently rewrite payloads (the hook API doesn't support in-place rewriting). For a silent, reversible rewrite, use the CLI pipe above.

Set `hook_decision: deny` in config to block instead of asking.

---

## Configuration

Override chain (lowest → highest priority):

```
bundled defaults → ~/.config/pii-scrub/config.yaml → ./.pii-scrub.yaml → CLI flags
```

Default config (`config.default.yaml`):

```yaml
languages: [en, fr]
models:
  en: en_core_web_lg
  fr: fr_core_news_lg
score_threshold: 0.5
entities: []          # empty = all entities Presidio recognizes
hook_decision: ask    # ask | deny | warn
```

### Adding a language

```bash
python -m spacy download de_core_news_lg
```

```yaml
# .pii-scrub.yaml
languages: [en, fr, de]
models:
  de: de_core_news_lg
```

---

## ⚠ Security: the mapping file holds real PII

`*.pii-map.json` contains the **original personal data** in plain text.

- pii-scrub writes mapping files with `0600` permissions (owner read/write only).
- The bundled `.gitignore` excludes `*.pii-map.json` and `*.pii-map.*`.
- **Never commit mapping files.**
- Delete them when you no longer need to restore.
- Use `--no-map` when reversibility isn't required.

---

## Development

```bash
git clone https://github.com/matinfo/pii-scrub
cd pii-scrub
pip install -e ".[dev]"
ruff check .
pytest -q
```

Unit tests stub out Presidio/spaCy and run entirely offline. For a live end-to-end check, run `pii-scrub download-models` first, then:

```bash
echo "Call John Smith at john@example.com" | pii-scrub scrub --map /tmp/test.pii-map.json
```

---

## License

MIT
