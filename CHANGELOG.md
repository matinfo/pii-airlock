# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- GitHub Copilot: `pii-airlock install-hook --target copilot` writes a `preToolUse` hook file
  for the Copilot CLI and cloud agent. The hook understands Copilot's payload (camelCase,
  `toolArgs` as JSON text), scans every tool argument and answers in Copilot's format.
  AGENTS.md documents VS Code custom-endpoint models through the gateway and what stays
  uncovered (default models, inline suggestions, prompts in the CLI).

## [0.5.0] - 2026-10-31

### Added
- Claude Code plugin: `/plugin marketplace add matinfo/pii-airlock`, then
  `/plugin install pii-airlock@pii-airlock`. Registers the hooks, adds a `/pii-airlock:setup`
  skill, and fails closed (blocks) when the CLI is not installed. A test keeps the plugin's
  hooks and version in step with `install-hook` and `pyproject.toml`.
- `pii-airlock scrub --encrypt-map` writes the mapping file encrypted (same scheme as the
  gateway's file store); `restore --map` detects and opens it with the machine's key.
- German and Italian identifiers: `DE_TAX_ID` (Steuer-IdNr., checksum + keyword), `DE_TAX_NUMBER`,
  and `IT_VAT_CODE` (`IT` prefix or `P.IVA` keyword, Luhn). National phone formats for
  Germany and Italy (`030 12345678`, `0170 1234567`, `06 12345678`, `333 1234567`).

### Fixed
- Presidio's `IT_VAT_CODE` fired on any 11-digit run, such as a German phone number: replaced
  by the stricter built-in rule. Phone numbers inside another identifier (IBAN, card, tax ID)
  are no longer reported separately.

## [0.4.0] - 2026-10-31

### Security
- Project config is no longer blindly trusted. A cloned repo's `.pii-airlock.yaml` /
  `SKILL.md` could ship `hook_on_error: open`, `entity_actions: {PERSON: allow}`,
  `passthrough_paths` or `mapping_dir` and switch protections off. Until you trust the
  project (`pii-airlock trust`; your own `allow` / `deny` / `action` edits keep a trusted
  project trusted, a `git pull` that changes the files does not) only settings that
  tighten apply: deny-list terms, custom patterns, `block`/`redact` actions, `deny` /
  `block` / `closed` decisions. `policy show` lists what is ignored.
- DOCX: footnotes, endnotes and comments that python-docx keeps as raw bytes are scrubbed
  too, plus comment and tracked-change authors, field codes and hyperlink targets.
- Propagation no longer blanks common words: a value found alone ("Will", "Server")
  matches its exact spelling only; name parts still match in any case.
- Header-profiled CSV columns now obey `entity_actions` (block / redact / allow); they used
  to be tokenized and stored in the mapping regardless. Redacted persons no longer reach
  surrogate fakes (and so the saved mapping).
- Gateway and `scrub` (CSV/JSON/DOCX): a value detected in one message (or cell) is now
  scrubbed in every other one, *earlier* ones included. Before, "Jean Dupont" found
  only in the last message left a bare "dupont" in an earlier message in clear.
- Gateway: OpenAI **Responses API** (Codex CLI) requests were forwarded with PII in
  clear; `input`, `instructions`, function-call arguments and outputs are now scrubbed,
  and `output[]` / `response.*.delta` events restored.
- Gateway: tool traffic is scrubbed for all providers — Anthropic `tool_use` /
  `tool_result` / text `document`, OpenAI `tool_calls` and `tool` messages, Gemini
  `functionCall` / `functionResponse`. Tool-call arguments are restored (JSON-escaped).
- Gateway now **fails closed**: bodies sent to endpoints it cannot scrub (file uploads,
  audio, …) are refused with 403, and non-JSON bodies on scrubbed endpoints with 400.
  New `passthrough_paths` config opts specific paths out.
- Gateway also scrubs embeddings, moderations, Anthropic `count_tokens` / message
  batches, and Gemini `countTokens` / `embedContent`.
- Detection now runs for **every configured language** and merges results; pattern
  recognizers (email, phone, IBAN, credit card, …) are registered for every language,
  so a non-English first language no longer disables them.
- Hooks: `Read` now scans the file content, not just its path; `Grep`, `WebFetch`,
  `WebSearch`, `NotebookEdit` and MCP tools are checked too.
- Hooks: prompts with PII are **blocked by default** (`prompt_decision: block`) and the
  user is shown a scrubbed version. Previously the prompt was sent with only a note to
  the model.
- Hooks **fail closed** when detection can't run (`hook_on_error: closed`), instead of
  silently letting the input through.

### Added
- Per-entity policy `entity_actions: {ENTITY: tokenize|redact|allow|block}` and
  `pii-airlock action ENTITY ACTION [--scope user]`: `redact` writes an irreversible
  `[ENTITY]` that never enters a mapping; `allow` ignores the type; `block` refuses
  the request (gateway 403, `scrub` exit 1 with nothing written, hooks deny and block
  prompts regardless of `hook_decision` / `prompt_decision`) without echoing the value.
  Accumulates across user and project policy; `exclude_entities` is now shorthand
  for `allow`.
- `ner_backend: gliner`: one multilingual GLiNER model (`gliner_model`, default
  `urchade/gliner_multi_pii-v1`) instead of a spaCy model per language; extra
  `pii-airlock[gliner]`, model fetched by `download-models`, shown in `doctor`. Long
  texts scanned in overlapping windows; patterns keep emails/phones/IDs. On the eval
  corpus: PERSON precision 0.95 (spaCy sm 0.68), overall 0.98 (0.67), recall 1.00.
- Eval harness: `--backend gliner`.
- Surrogate mode (`token_style: surrogate`): realistic, stable fakes instead of tokens
  (`Jasper Iverson`, `jasper.iverson@example.com`, same-shape phones, Luhn-valid cards,
  checksum-valid IBANs, RFC 5737 IPs), restored in responses, streams (fakes split
  across chunks) and tool-call arguments. Name parts and email local parts share the
  full name's fakes. Fakes never collide with the input or each other; other
  entities keep tokens. Mapping files (v2) store the fakes.
- Stable tokens (default): `<PERSON_558644>` is an HMAC of the value with a local key
  (`~/.local/state/pii-airlock/token.key`, owner-only), so a value keeps one token
  across requests, files, processes, trimmed histories and subagents, and prompt
  caches keep hitting. `token_rotation: day|week|never` (default `day`: unlinkable
  across days). `token_style: sequential` restores `<PERSON_1>` numbering.
- Hook daemon: hooks no longer load the spaCy models on every tool call (0.5-3 s).
  The first call starts a background daemon (Unix socket, user-only, idle exit after
  `hook_daemon_idle_minutes`); later calls take ~60 ms. Project policy is reloaded per
  call, a daemon running older code steps aside, failures still fail closed.
  `pii-airlock daemon start|stop|status|run`, shown in `doctor`. `hook_daemon: off`
  disables it (no daemon on Windows).
- `hook_fallback: regex`: when no daemon answers, hooks can use patterns only
  (emails, phones, IBAN, cards, IPs, IDs, secrets, deny list) instead of loading
  models; names and places are not detected in that mode.
- Analysis cache: model findings are remembered per text (by digest, no copy of the
  text kept), so the conversation history chat clients resend on every turn is not
  analyzed again (~8x faster on a 20-turn chat). `analysis_cache_size`, 0 disables.
- Batched analysis: the gateway, `scrub` on CSV/JSON/DOCX and hook file scans run
  all their strings through spaCy as one batch (about 2x faster than one by one).
- Detection eval harness (`tests/eval`): labeled EN+FR corpus of fake PII, per-entity
  recall / precision / leak-free report (`python -m tests.eval.run_eval -v`) and a CI job
  that fails below `thresholds.json`.
- Built-in recognizers (regex + checksum, every language): French NIR, Swiss AHV/AVS,
  SIRET/SIREN, FR/CH national phone formats, and secrets (cloud/API keys, JWTs,
  private keys, URL and assignment passwords). `builtin_recognizers: false` disables.
- Per-project policy in `.claude/skills/pii-airlock/SKILL.md` (a Claude Code skill plus
  a `yaml pii-airlock` config block); user-level skill for personal rules.
- Policy keys `allow_list`, `deny_list`, `custom_patterns`, accumulated across layers.
- Commands `pii-airlock policy init|show`, `pii-airlock allow`, `pii-airlock deny`.
  Hook messages show the one-command fix for a false positive.
- Mapping files are encrypted at rest (AES-256-GCM, key derived from `token.key`) with the
  file mapping backend. `mapping_encryption: false` opts out; existing plain files still load.
  New dependency: `cryptography`.

### Changed
- Tokens default to the stable format (`<PERSON_558644>` instead of `<PERSON_1>`);
  set `token_style: sequential` for the old numbering.
- Other mentions of a detected value are scrubbed too, including parts of person
  names ("Dupont" after "Jean Dupont"), and values found earlier in the same
  request or file. NER often finds a name once and misses the rest.
- CSV: columns whose header marks personal data (`Nom`, `Prénom`, `email`,
  `Téléphone`, `IBAN`, `date of birth`, …, EN/FR/DE) are tokenized cell by cell,
  even when NER can't recognize a lone value; the header row is kept.
- Tokens are numbered in reading order (`<PERSON_1>` is the first person mentioned).
- Noisy entity types are skipped by default (`exclude_entities`: `DATE_TIME`, `URL`,
  `NRP`, `US_DRIVER_LICENSE`, `US_BANK_NUMBER`, `US_PASSPORT`,
  `IN_VEHICLE_REGISTRATION`): every web fetch, date or long number in a command used
  to trigger a hook prompt. List one in `entities` (or set `exclude_entities: []`)
  to keep it. New `score_thresholds` sets a minimum score per entity type.
- A weekly CI job (`eval-gliner.yml`, also manual) runs the eval with the GLiNER backend
  against `tests/eval/thresholds-gliner.json`, without the torch install on every push.
- The eval corpus covers German and Italian too (`de_core_news_sm`, `it_core_news_sm`).

### Fixed
- Hooks apply the policy of the project Claude Code reports (event `cwd`), not the
  hook process's directory; a malformed policy block fails closed instead of crashing
  the hook.
- Streaming restore keeps one buffer per choice / content block / tool call, and
  releases held-back text before the block or choice ends — no more synthetic chunk
  after `message_stop` / `[DONE]` and no missing `event:` line (Anthropic SDK errors).
- `install-hook` upgrades the tool matcher of an existing pii-airlock entry.
- International phone numbers (`+49 30 ...`, `+39 02 ...`) leaked in German and Italian
  text: Presidio scores a bare number 0.4 and only boosts it on English context words.
  A built-in rule now catches any `+CC` number.
- Digit groups inside an IBAN or card number are no longer also reported as a phone number.

## [0.2.3] - 2026-06-20

### Fixed
- Test-suite noise cleanup: proxy tests now suppress the Starlette TestClient
  import deprecation warning without breaking Ruff import-order checks.
- Pytest warning-filter misconfiguration was removed to avoid repeated
  `PytestConfigWarning` spam.

## [0.2.2] - 2026-06-20

### Fixed
- `download-models` in pip-less environments (common with `pipx`) now exits
  successfully when configured models are already installed, instead of always
  failing.

### Changed
- README and AGENTS docs now include user-first troubleshooting for common
  setup errors (`bad interpreter`, `No module named spacy`, missing proxy deps).

### Added
- Pluggable mapping stores (`memory` and `file`) with a shared factory, plus
  proxy wiring for configurable mapping backends (`mapping_backend`,
  `mapping_dir`) to support more scalable deployment patterns.
- New usability commands:
  - `pii-airlock init` for guided first-time gateway setup
  - `pii-airlock doctor` for one-command local health checks

## [0.2.1] - 2026-06-20

### Fixed
- **pipx compatibility:** added an explicit `click>=8.0` runtime dependency so
  `pii-airlock download-models` no longer fails in isolated installs with
  `ModuleNotFoundError: click`.
- **Model installer reliability:** `download-models` now detects pip-less
  interpreters (common with `pipx`) and prints exact `pipx inject` commands for
  each model wheel instead of running a no-op install path.
- **Model install verification:** after each `spacy download`, installation is
  now verified in a fresh interpreter. If verification fails, the command exits
  non-zero and prints direct wheel-install fallback commands.

## [0.2.0] - 2026-06-20

### Added
- **Universal gateway** (`pii-airlock proxy`): a local reverse proxy that scrubs
  PII out of outbound requests and restores it in responses (including SSE
  streams), for any provider. Base-URL shim — no TLS interception.
- **Payload adapters** (`pii_scrub/payload.py`): provider-agnostic core with
  OpenAI-compatible, Anthropic, and Gemini adapters. Adding a provider is one
  small adapter.
- `StreamRestorer` reassembles placeholder tokens split across stream chunks.
- `[proxy]` optional dependency group (httpx, starlette, uvicorn).
- `AGENTS.md` per-agent integration guide; SECURITY, CONTRIBUTING, CODE_OF_CONDUCT.

### Changed
- Detection is now serialized with a lock so the engine is safe to share across
  threads (used by the gateway).
- Mapping files are created `0600` atomically via `os.open` (no world-readable
  window on POSIX).
- README rewritten for accuracy: explicit guarantees & limitations; the false
  "no data ever leaves your machine" blanket claim was removed (the gateway
  forwards *scrubbed* traffic).
- CI now runs on Linux, macOS and Windows.

### Removed
- Unused `csv` extra (CSV/JSON handling uses the standard library).

## [0.1.0] - 2026-06-20

### Added
- Reversible CLI: `scrub`, `restore`, `detect`, `download-models`.
- Deterministic placeholder tokens (`<TYPE_N>`) with a reversible mapping store.
- Multilingual detection on Microsoft Presidio + spaCy (English + French defaults).
- Format handlers: plain text, CSV, JSON (stdlib), `.docx` and PDF (optional extras).
- Claude Code guardrail hooks: `PreToolUse` and `UserPromptSubmit`, plus
  `install-hook`.
- Config override chain: bundled defaults → user → project → CLI flags.

[Unreleased]: https://github.com/matinfo/pii-airlock/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/matinfo/pii-airlock/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/matinfo/pii-airlock/compare/v0.2.3...v0.4.0
[0.2.3]: https://github.com/matinfo/pii-airlock/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/matinfo/pii-airlock/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/matinfo/pii-airlock/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/matinfo/pii-airlock/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/matinfo/pii-airlock/releases/tag/v0.1.0
