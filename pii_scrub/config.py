"""Configuration loading and merging.

Override chain (lowest -> highest priority):
    bundled config.default.yaml
    ~/.config/pii-airlock/config.yaml
    ~/.claude/skills/pii-airlock/SKILL.md      (policy block, see policy.py)
    ./.pii-airlock.yaml
    ./.claude/skills/pii-airlock/SKILL.md      (policy block)
    CLI flags (applied by the caller)

`allow_list`, `deny_list` and `custom_patterns` accumulate across layers (your
personal allow list + the project's), every other key is overridden.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

from .policy import normalize_deny, read_policy, skill_path

# Shipped inside the package so it is always found, however pii-airlock is installed.
_DEFAULT_FILE = Path(__file__).resolve().parent / "config.default.yaml"
_CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
_USER_FILE = _CONFIG_HOME / "pii-airlock" / "config.yaml"
_PROJECT_NAME = ".pii-airlock.yaml"

# Built-in defaults. These make pii-airlock work even if no config file is found,
# so an install can never end up with an empty model map. The bundled
# config.default.yaml mirrors these for users to copy and override.
_DEFAULT_MODELS = {"en": "en_core_web_lg", "fr": "fr_core_news_lg"}


@dataclass(frozen=True)
class Config:
    languages: list[str] = field(default_factory=lambda: ["en", "fr"])
    models: dict[str, str] = field(default_factory=lambda: dict(_DEFAULT_MODELS))
    score_threshold: float = 0.5
    entities: list[str] = field(default_factory=list)
    hook_decision: str = "ask"
    prompt_decision: str = "block"
    hook_on_error: str = "closed"
    hook_max_file_bytes: int = 2_000_000
    passthrough_paths: list[str] = field(default_factory=list)
    mapping_backend: str = "memory"
    mapping_dir: str | None = None
    allow_list: list[str] = field(default_factory=list)
    deny_list: dict[str, list[str]] = field(default_factory=dict)
    custom_patterns: list[dict[str, Any]] = field(default_factory=list)

    def merged_with(self, data: dict[str, Any]) -> Config:
        """Return a copy with non-None keys from `data` applied."""
        clean = {k: v for k, v in data.items() if v is not None and k in self.__dataclass_fields__}
        if "allow_list" in clean:
            clean["allow_list"] = _union(self.allow_list, [str(t) for t in clean["allow_list"]])
        if "deny_list" in clean:
            deny = {k: list(v) for k, v in self.deny_list.items()}
            for entity, terms in normalize_deny(clean["deny_list"]).items():
                deny[entity] = _union(deny.get(entity, []), terms)
            clean["deny_list"] = deny
        if "custom_patterns" in clean:
            clean["custom_patterns"] = [*self.custom_patterns, *clean["custom_patterns"]]
        return replace(self, **clean)


def _union(base: list[str], extra: list[str]) -> list[str]:
    seen = {t.casefold() for t in base}
    out = list(base)
    for term in extra:
        if term.casefold() not in seen:
            seen.add(term.casefold())
            out.append(term)
    return out


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_config(
    overrides: dict[str, Any] | None = None, cwd: str | Path | None = None
) -> Config:
    """Build a Config from the default file, then user/project layers, then overrides.

    `cwd` is the project directory (defaults to the current directory); hooks
    pass the directory Claude Code reports, so the right project policy applies.
    """
    project = Path(cwd) if cwd else Path.cwd()
    cfg = Config().merged_with(_read_yaml(_DEFAULT_FILE))
    cfg = cfg.merged_with(_read_yaml(_USER_FILE))
    cfg = cfg.merged_with(read_policy(skill_path("user")))
    cfg = cfg.merged_with(_read_yaml(project / _PROJECT_NAME))
    cfg = cfg.merged_with(read_policy(skill_path("project", project)))
    if overrides:
        cfg = cfg.merged_with(overrides)
    return cfg
