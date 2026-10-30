# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security
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
- Built-in recognizers (regex + checksum, every language): French NIR, Swiss AHV/AVS,
  SIRET/SIREN, FR/CH national phone formats, and secrets (cloud/API keys, JWTs,
  private keys, URL and assignment passwords). `builtin_recognizers: false` disables.
- Per-project policy in `.claude/skills/pii-airlock/SKILL.md` (a Claude Code skill plus
  a `yaml pii-airlock` config block); user-level skill for personal rules.
- Policy keys `allow_list`, `deny_list`, `custom_patterns`, accumulated across layers.
- Commands `pii-airlock policy init|show`, `pii-airlock allow`, `pii-airlock deny`.
  Hook messages show the one-command fix for a false positive.

### Changed
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

### Fixed
- Hooks apply the policy of the project Claude Code reports (event `cwd`), not the
  hook process's directory; a malformed policy block fails closed instead of crashing
  the hook.
- Streaming restore keeps one buffer per choice / content block / tool call, and
  releases held-back text before the block or choice ends — no more synthetic chunk
  after `message_stop` / `[DONE]` and no missing `event:` line (Anthropic SDK errors).
- `install-hook` upgrades the tool matcher of an existing pii-airlock entry.

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

[Unreleased]: https://github.com/matinfo/pii-airlock/compare/v0.2.3...HEAD
[0.2.3]: https://github.com/matinfo/pii-airlock/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/matinfo/pii-airlock/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/matinfo/pii-airlock/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/matinfo/pii-airlock/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/matinfo/pii-airlock/releases/tag/v0.1.0
