# pii-scrub

Local, **reversible** PII anonymizer built on [Microsoft Presidio](https://microsoft.github.io/presidio/).  
Keep real personal data off LLM round-trips — replace it with stable placeholder tokens, send the scrubbed text to the model, then swap the originals back in from a local mapping file.

**Detection and substitution run entirely on your machine.** The CLI pipe and the Claude Code hooks send nothing anywhere. The optional gateway *does* forward traffic to the provider you point it at — but only **after** PII has been replaced with tokens. Real personal data never reaches the provider.

Runs on **macOS, Linux and Windows**, Python ≥ 3.10.

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
  the real HTTPS call upstream. No certificates to install. Bind stays on `127.0.0.1` by default.
- **Auth passes through** untouched and pii-scrub never logs request headers or bodies.
  (uvicorn runs at log level `warning`, so request lines aren't logged either.)
- A **fresh in-memory mapping per request** — the gateway writes nothing to disk.
- **Concurrency-safe:** detection is serialized with a lock, so the engine is shared
  safely across simultaneous requests.

**Provider coverage** — three wire formats, each with an adapter in `pii_scrub/payload.py`:

| Route | Wire format | Covers | Streaming |
|---|---|---|---|
| `/openai` | OpenAI Chat Completions | OpenAI, Codex, Cursor, Continue, Ollama, LiteLLM, vLLM, … | SSE ✅ |
| `/anthropic` | Anthropic Messages | Claude SDKs, Claude-compatible tools | SSE ✅ |
| `/gemini` | Gemini generateContent | Google Gemini | SSE ✅ · array-stream buffered |

Adapters are verified by unit + integration tests (mocked upstream) against each
provider's documented request/response shapes. Adding a provider = one small adapter.

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
hook_decision: ask    # ask (surface + confirm) | deny (block)
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

## Guarantees & limitations

**What pii-scrub guarantees**

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
  spacing). pii-scrub reduces exposure — it is **not** a guarantee that every piece of
  PII is removed. Review sensitive material; raise `score_threshold` or add custom
  recognizers as needed.
- **Gateway scope.** Only generation endpoints are scrubbed (chat/messages/generateContent).
  Embeddings and other endpoints pass through unchanged. Tokens are restored in message
  **content**, not inside tool-call/function arguments a model may emit.
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
