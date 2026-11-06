---
name: setup
description: Set up or check pii-airlock, the PII guard for this project. Use when the user asks to install, verify, configure or troubleshoot pii-airlock, or sets a per-project policy for personal data.
---

# pii-airlock setup

The plugin's hooks call the `pii-airlock` CLI. Work through these steps and stop at the first failure.

1. **CLI installed?** Run `pii-airlock --version`. If missing, ask the user to install it:
   `brew install matinfo/tap/pii-airlock` or `pipx install pii-airlock`.
   Until then the hooks block every prompt and tool call in guarded projects (fail closed).
2. **Project guarded?** Run `pii-airlock status`. If it says `off`, ask the user before running
   `pii-airlock init` in the project root: it creates `.pii-airlock/` (policy + local maps) and
   downloads the detection models (a few hundred MB, once). It sees the plugin and does not
   install duplicate hooks.
3. **Project policy (optional).** Lives in `.pii-airlock/config.yaml`; `pii-airlock status` shows it.
   - `pii-airlock allow "<value>"` / `deny "<value>"` edit the allow and deny lists.
   - `pii-airlock action PERSON redact` (or `tokenize`, `allow`, `block`) sets what happens per entity type.
4. **Project config from a cloned repo is untrusted** until the user reviews it and runs
   `pii-airlock trust`. Never run `trust` on the user's behalf for a repo they did not write.
5. **Pause:** `pii-airlock off` / `pii-airlock on`, only when the user asks.

Never print or open files under `.pii-airlock/maps/` or `*.pii-map.json`: they hold the real values.
