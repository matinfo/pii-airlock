"""Per-project PII policy, kept in a Claude Code skill.

One file serves two readers:

* **Claude** loads ``.claude/skills/pii-airlock/SKILL.md`` as a skill, so the
  agent knows the project's rules (what is sensitive, what to do when a hook
  blocks, never to read mapping files).
* **pii-airlock** reads the fenced ``yaml pii-airlock`` block in the same file
  as a config layer (allow/deny lists, custom patterns, entities, decisions).

A user-level skill (``~/.claude/skills/pii-airlock/SKILL.md``) holds personal
rules (e.g. your own name in ``allow_list``) shared by every project.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

SKILL_RELPATH = Path(".claude") / "skills" / "pii-airlock" / "SKILL.md"

# ```yaml pii-airlock  ...  ```
_BLOCK_RE = re.compile(r"^```ya?ml[ \t]+pii-airlock[ \t]*\n(.*?)^```[ \t]*$", re.M | re.S)

DEFAULT_DENY_ENTITY = "CONFIDENTIAL"


class PolicyError(ValueError):
    """The policy block in a SKILL.md is malformed."""


def skill_path(scope: str = "project", cwd: str | Path | None = None) -> Path:
    if scope == "user":
        return Path.home() / SKILL_RELPATH
    return Path(cwd or Path.cwd()) / SKILL_RELPATH


def read_policy(path: Path) -> dict[str, Any]:
    """Return the policy mapping from a SKILL.md, or {} if absent."""
    if not path.is_file():
        return {}
    match = _BLOCK_RE.search(path.read_text(encoding="utf-8"))
    if not match:
        return {}
    try:
        data = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise PolicyError(f"{path}: invalid YAML in the pii-airlock policy block: {exc}") from exc
    if not isinstance(data, dict):
        raise PolicyError(f"{path}: the pii-airlock policy block must be a YAML mapping")
    return data


def init_skill(path: Path, *, force: bool = False) -> bool:
    """Write the policy skill template. Returns False if it already exists."""
    if path.exists() and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_TEMPLATE.format(block=_dump({"allow_list": [], "deny_list": {}})),
                    encoding="utf-8")
    return True


def add_allow(path: Path, term: str) -> bool:
    """Add `term` to the allow list. Returns False if it was already there."""
    def change(data: dict) -> bool:
        items = data.setdefault("allow_list", []) or []
        if any(_same(term, t) for t in items):
            return False
        data["allow_list"] = [*items, term]
        return True

    return _update(path, change)


def add_deny(path: Path, term: str, entity: str = DEFAULT_DENY_ENTITY) -> bool:
    """Add `term` to the deny list under `entity`. Returns False if already there."""
    entity = entity.upper()

    def change(data: dict) -> bool:
        deny = normalize_deny(data.get("deny_list"))
        if any(_same(term, t) for terms in deny.values() for t in terms):
            return False
        deny.setdefault(entity, []).append(term)
        data["deny_list"] = deny
        return True

    return _update(path, change)


def set_action(path: Path, entity: str, action: str) -> bool:
    """Set the `entity_actions` policy for `entity`. Returns False if unchanged."""
    from .config import normalize_actions

    try:
        (entity, action), = normalize_actions({entity: action}).items()
    except ValueError as exc:
        raise PolicyError(str(exc)) from None

    def change(data: dict) -> bool:
        actions = dict(data.get("entity_actions") or {})
        if actions.get(entity) == action:
            return False
        actions[entity] = action
        data["entity_actions"] = actions
        return True
    return _update(path, change)


def normalize_deny(value: Any) -> dict[str, list[str]]:
    """``deny_list`` accepts a plain list (-> CONFIDENTIAL) or ``{ENTITY: [terms]}``."""
    if not value:
        return {}
    if isinstance(value, list):
        return {DEFAULT_DENY_ENTITY: [str(v) for v in value]}
    if isinstance(value, dict):
        return {str(k).upper(): [str(v) for v in (vs or [])] for k, vs in value.items()}
    raise PolicyError("deny_list must be a list of terms or a mapping ENTITY: [terms]")


def _same(a: str, b: str) -> bool:
    return a.casefold().strip() == str(b).casefold().strip()


def _dump(data: dict) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False)


def _update(path: Path, change) -> bool:
    if not path.is_file():
        init_skill(path)
    text = path.read_text(encoding="utf-8")
    data = read_policy(path)
    if not change(data):
        return False
    block = _dump(data)
    if _BLOCK_RE.search(text):
        text = _BLOCK_RE.sub(lambda _m: f"```yaml pii-airlock\n{block}```", text, count=1)
    else:
        text = text.rstrip("\n") + f"\n\n## Policy\n\n```yaml pii-airlock\n{block}```\n"
    path.write_text(text, encoding="utf-8")
    return True


_TEMPLATE = """\
---
name: pii-airlock
description: >-
  Personal-data (PII) policy for this project, enforced by pii-airlock. Use when
  handling customer, employee or user data, when reading files that may contain
  personal data, and whenever a pii-airlock hook blocks or asks about a prompt
  or tool call.
---

# Personal-data policy

This project uses **pii-airlock** to keep personal data (names, emails, phone
numbers, IBANs, national IDs, client names, ...) out of LLM traffic. Its hooks
check prompts and tool calls; the policy block at the end of this file tells it
what counts as sensitive here.

## Rules for Claude

- Do not copy personal data into prompts, shell commands, commit messages,
  code, tests or docs. Use obvious placeholders instead (`Jane Doe`,
  `jane@example.com`, `+41 00 000 00 00`).
- When a pii-airlock hook asks or blocks, **do not work around it** (no
  re-encoding, splitting or paraphrasing the value). Tell the user what was
  flagged and let them decide.
- To work on a file that contains personal data, suggest scrubbing it first:
  `pii-airlock scrub data.csv -o data.scrubbed.csv --map data.pii-map.json`,
  then work on the scrubbed copy; `pii-airlock restore` puts real values back.
- Never read, print or commit `*.pii-map.json` files: they hold the real values.
- Never edit the policy below or run `pii-airlock allow` / `pii-airlock deny`
  unless the user asks you to.

## Policy

Read by pii-airlock. Edit by hand or with `pii-airlock allow "Acme SA"` /
`pii-airlock deny "Project Phoenix"`. Keys:

- `allow_list`: terms that are never PII here (your company, product names,
  public figures). Detections inside these terms are ignored.
- `deny_list`: terms that are always sensitive here (client names, code
  names), as a list or grouped by label (`CLIENT: [...]`). Matched
  case-insensitively, as whole words.
- `custom_patterns`: regexes for project identifiers, e.g.
  `- {{entity: CONTRACT_ID, regex: 'CT-\\d{{6}}'}}`.
- `entity_actions`: what happens to each entity type: `tokenize` (default,
  reversible), `redact` (irreversible `[TYPE]`, never stored), `allow` (left
  alone) or `block` (the request or prompt is refused). Set with
  `pii-airlock action IBAN_CODE redact`.
- Any other pii-airlock setting (`entities`, `score_threshold`,
  `hook_decision`, `prompt_decision`, ...) can be set here for this project.

```yaml pii-airlock
{block}```
"""
