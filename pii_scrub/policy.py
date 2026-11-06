"""Project policy: ``.pii-airlock/config.yaml`` (see project.py).

A plain YAML file holding any pii-airlock setting; the usual ones are the allow
and deny lists, custom patterns and per-entity actions. ``pii-airlock allow``,
``deny`` and ``action`` edit it (comment lines at the top are kept). The user
config (``~/.config/pii-airlock/config.yaml``) has the same format and is edited
the same way with ``--scope user``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

DEFAULT_DENY_ENTITY = "CONFIDENTIAL"


class PolicyError(ValueError):
    """The policy block in a SKILL.md is malformed."""


def read_policy(path: Path) -> dict[str, Any]:
    """The settings in a policy/config file, or {} if absent."""
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise PolicyError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise PolicyError(f"{path}: must be a YAML mapping of settings")
    return data


def write_template(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_TEMPLATE + _dump({"allow_list": [], "deny_list": {}}), encoding="utf-8")


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
        write_template(path)
    text = path.read_text(encoding="utf-8")
    data = read_policy(path)
    if not change(data):
        return False
    header = []
    for line in text.splitlines(keepends=True):
        if not line.startswith("#") and line.strip():
            break
        header.append(line)
    path.write_text("".join(header) + _dump(data), encoding="utf-8")
    return True


_TEMPLATE = """\
# pii-airlock policy for this project. Committed with the repo, shared with the team.
# Edit by hand, or: pii-airlock allow "Acme SA" | deny "Project X" | action IBAN_CODE redact
#
#   allow_list       terms never treated as PII here (your company, products, public figures)
#   deny_list        terms always sensitive here (client names, code names), a list
#                    or grouped by label: {CLIENT: [...]}; whole words, any case
#   custom_patterns  project identifiers: - {entity: CONTRACT_ID, regex: 'CT-\\d{6}'}
#   entity_actions   per entity type: tokenize (default) | redact | allow | block
#   Any other setting (entities, score_threshold, hook_decision, ...) also works here.
#
# Settings that let more through (allow_list, entity_actions: allow, ...) apply only
# once you trust this file: `pii-airlock trust`. Teammates' edits need a new `trust`.

"""
