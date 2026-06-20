# Security Policy

pii-airlock is a privacy tool. We take its security and its honest limitations
seriously.

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Report privately via GitHub's **["Report a vulnerability"](https://github.com/matinfo/pii-scrub/security/advisories/new)**
button (repository → *Security* → *Advisories*). We aim to acknowledge within
72 hours and to publish a fix and advisory once a patch is available.

When reporting, please include: affected version, platform, a minimal
reproduction, and the impact you observed.

## Threat model — what pii-airlock protects against

pii-airlock reduces the chance that real personal data reaches an LLM provider:

- **CLI pipe** and **Claude Code hooks** run fully locally and send nothing.
- **Gateway** forwards traffic to the provider you configure, but only *after*
  detected PII is replaced with placeholder tokens.

## Important limitations — please read

- **Detection is best-effort, not complete.** Presidio + spaCy are statistical
  models. They miss entities, mis-classify them, and vary by language and model
  size. pii-airlock **lowers** exposure; it is **not** a guarantee that all PII is
  removed. Do not rely on it as a sole control for regulated data. Review
  sensitive material and tune `score_threshold` / custom recognizers.
- **The mapping file contains real PII in plain text.** It is the most sensitive
  artifact pii-airlock produces. It is created owner-only (`0600` on POSIX; default
  user ACLs on Windows) and is git-ignored. Never commit it; delete it when done;
  use `--no-map` when you don't need to restore.
- **The gateway sees your provider API keys** (they pass through in request
  headers). pii-airlock never logs request headers or bodies, runs uvicorn at log
  level `warning`, and binds to `127.0.0.1` by default. Do not expose the proxy
  on a public interface.
- **Scope:** the gateway scrubs generation endpoints only; tool-call/function
  arguments a model emits are not restored.

## Supported versions

Security fixes target the latest released version on the `main` branch.
