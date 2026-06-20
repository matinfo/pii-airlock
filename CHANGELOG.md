# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/matinfo/pii-airlock/compare/v0.2.2...HEAD
[0.2.2]: https://github.com/matinfo/pii-airlock/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/matinfo/pii-airlock/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/matinfo/pii-airlock/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/matinfo/pii-airlock/releases/tag/v0.1.0
