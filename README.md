# pii-scrub

Local, **reversible** PII anonymizer built on [Microsoft Presidio](https://microsoft.github.io/presidio/).  
Keep real personal data off LLM round-trips — replace it with stable placeholder tokens, send the scrubbed text to the model, then swap the originals back in from a local mapping file.

Everything runs **100% locally**. No data ever leaves your machine.

---

## Two workflows

| Workflow | What it does |
|---|---|
| **CLI pipe** | `pii-scrub scrub` → LLM → `pii-scrub restore` — reversible, scriptable |
| **Claude Code hooks** | Detect PII before it reaches the model, on prompts *and* tool data |

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
pipx inject pii-scrub 'pii-scrub[docx]'   # Word .docx
pipx inject pii-scrub 'pii-scrub[pdf]'    # PDF (text extraction)
pipx inject pii-scrub 'pii-scrub[all]'    # both
```

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
