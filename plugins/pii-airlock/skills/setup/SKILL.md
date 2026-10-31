---
name: setup
description: Set up or check pii-airlock, the PII guard for this project. Use when the user asks to install, verify, configure or troubleshoot pii-airlock, or sets a per-project policy for personal data.
---

# pii-airlock setup

The plugin's hooks call the `pii-airlock` CLI. Work through these steps and stop at the first failure.

1. **CLI installed?** Run `pii-airlock --version`. If missing, ask the user to install it:
   `brew install matinfo/tap/pii-airlock` or `pipx install "pii-airlock[proxy]"`.
   Until then the hooks block every prompt and tool call (fail closed).
2. **Models downloaded?** Run `pii-airlock doctor`. If a spaCy model is missing, run
   `pii-airlock download-models` (a few hundred MB, once).
3. **Project policy (optional).** `pii-airlock policy show` prints the active policy.
   - `pii-airlock policy init` creates `.claude/skills/pii-airlock/SKILL.md` for this project.
   - `pii-airlock allow "<value>"` / `deny "<value>"` edit the allow and deny lists.
   - `pii-airlock action PERSON redact` (or `tokenize`, `allow`, `block`) sets what happens per entity type.
4. **Project config from a cloned repo is untrusted** until the user reviews it and runs
   `pii-airlock trust`. Never run `trust` on the user's behalf for a repo they did not write.

Never print or open `*.pii-map.json` files: they hold the real values.
