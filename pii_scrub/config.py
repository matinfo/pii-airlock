"""Configuration loading and merging.

Override chain (lowest -> highest priority):
    bundled config.default.yaml
    ~/.config/pii-airlock/config.yaml
    ./.pii-airlock.yaml
    CLI flags (applied by the caller)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

# Shipped inside the package so it is always found, however pii-airlock is installed.
_DEFAULT_FILE = Path(__file__).resolve().parent / "config.default.yaml"
_CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
_USER_FILE = _CONFIG_HOME / "pii-airlock" / "config.yaml"
_PROJECT_FILE = Path.cwd() / ".pii-airlock.yaml"

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

    def merged_with(self, data: dict[str, Any]) -> Config:
        """Return a copy with non-None keys from `data` applied."""
        clean = {k: v for k, v in data.items() if v is not None and k in self.__dataclass_fields__}
        return replace(self, **clean)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_config(overrides: dict[str, Any] | None = None) -> Config:
    """Build a Config from the default file, then user/project files, then overrides."""
    cfg = Config().merged_with(_read_yaml(_DEFAULT_FILE))
    cfg = cfg.merged_with(_read_yaml(_USER_FILE))
    cfg = cfg.merged_with(_read_yaml(_PROJECT_FILE))
    if overrides:
        cfg = cfg.merged_with(overrides)
    return cfg
