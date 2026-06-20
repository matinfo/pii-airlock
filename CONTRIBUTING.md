# Contributing to pii-airlock

Thanks for helping make PII safer for AI workflows. Contributions of all kinds
are welcome: bug reports, docs, new language configs, and new provider adapters.

## Quick start

```bash
git clone https://github.com/matinfo/pii-scrub
cd pii-airlock
python -m venv .venv && . .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev,all]"
```

## Before you open a PR

```bash
ruff check .        # lint (also: ruff format .)
pytest -q           # unit + integration tests, fully offline
```

Both must pass. CI runs them on Linux (Python 3.10–3.14) and on macOS + Windows.

- Tests stub Presidio/spaCy, so they need no model download and no network.
- Keep new code lint-clean and add tests for new behavior.
- Match the surrounding style (type hints, `from __future__ import annotations`,
  small focused modules).

## Good first contributions

- **Add a language.** spaCy ships models for many languages — see the README
  "Adding a language". A docs PR listing a working `{lang: model}` pair is useful.
- **Add a provider adapter.** Implement a `PayloadAdapter` in
  `pii_scrub/payload.py` (one class: where user text lives in the request, where
  model text lives in the response) and register it. Add tests in
  `tests/test_payload.py` mirroring the existing ones. See `AGENTS.md`.
- **Custom recognizers** to improve detection (e.g. locale-specific phone/ID
  formats) via Presidio's recognizer registry.

## Commit & PR conventions

- Conventional-commit style subjects are appreciated (`feat:`, `fix:`, `docs:`…).
- Describe the user-facing change and how you verified it.
- One logical change per PR where practical.

## Reporting bugs / security

- Bugs: open an issue using the template.
- Security vulnerabilities: **do not** open a public issue — see
  [SECURITY.md](SECURITY.md).

By contributing you agree your contributions are licensed under the project's
[MIT License](LICENSE).
