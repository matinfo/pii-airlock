# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- **Packaging:** `config.default.yaml` is now shipped inside the package and the
  built-in `Config` carries default model mappings. Previously a non-editable
  install (PyPI / `pipx`) could load an empty model map and fail with "No spaCy
  models configured". Now a fresh install works out of the box.

### Added
- Community layer: README badges, `AGENTS.md` (per-agent integration matrix),
  `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md`, issue/PR
  templates, Dependabot, and a PyPI trusted-publishing release workflow.

## [0.2.0] - 2026-06-20

### Added
- **Universal gateway** (`pii-scrub proxy`): a local reverse proxy that scrubs
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

[Unreleased]: https://github.com/matinfo/pii-scrub/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/matinfo/pii-scrub/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/matinfo/pii-scrub/releases/tag/v0.1.0
