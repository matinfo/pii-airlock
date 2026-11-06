"""The project home: one ``.pii-airlock/`` folder, created by ``pii-airlock init``.

    my-project/.pii-airlock/
      config.yaml   project policy (allow/deny lists, actions, patterns): committed
      .gitignore    keeps everything else out of git
      maps/         mapping files from `scrub` (real PII, encrypted, local only)
      off           present = paused on this machine (`pii-airlock off`)

Like CodeGraph's ``.codegraph/``, the folder is also the switch: the hooks run
only in a directory at or below a project home (unless ``activation: always``),
so they can be installed once for the user and stay silent everywhere else.

What must not live in the project stays in the user state dir: the token key
(maps next to their key would protect nothing) and trust decisions (a repo
must not be able to ship its own).
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

HOME = ".pii-airlock"
CONFIG = "config.yaml"
_PAUSED = "off"
_GITIGNORE = (
    "# Only the policy is shared. Mapping files hold real PII: never commit them.\n"
    "*\n!.gitignore\n!config.yaml\n"
)


def find_project(start: str | Path | None = None) -> Path | None:
    """Nearest directory at or above `start` holding a project home, else None."""
    here = Path(start).expanduser() if start else Path.cwd()
    try:
        here = here.resolve()
    except OSError:
        return None
    for directory in (here, *here.parents):
        if (directory / HOME).is_dir():
            return directory
    return None


def home(root: str | Path) -> Path:
    return Path(root) / HOME


def config_path(root: str | Path) -> Path:
    return home(root) / CONFIG


def maps_dir(root: str | Path) -> Path:
    return home(root) / "maps"


def is_paused(root: str | Path) -> bool:
    return (home(root) / _PAUSED).exists()


def is_active(start: str | Path | None, activation: str) -> bool:
    """Should the hooks run here? A paused project wins over `activation: always`."""
    root = find_project(start)
    if root is not None:
        return not is_paused(root)
    return activation == "always"


def init_project(root: str | Path) -> bool:
    """Create (or complete) the project home and un-pause it. True if newly created."""
    from .policy import write_template

    folder = home(root)
    created = not folder.is_dir()
    folder.mkdir(parents=True, exist_ok=True)
    ignore = folder / ".gitignore"
    if not ignore.is_file():
        ignore.write_text(_GITIGNORE, encoding="utf-8")
    if not config_path(root).is_file():
        write_template(config_path(root))
    private_dir(maps_dir(root))
    resume(root)
    return created


def private_dir(path: Path) -> Path:
    """Create an owner-only directory (mapping files hold real PII)."""
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(path, 0o700)
    return path


def pause(root: str | Path) -> bool:
    """True if the project was running."""
    flag = home(root) / _PAUSED
    if flag.exists():
        return False
    flag.write_text("Paused by `pii-airlock off`. `pii-airlock on` resumes.\n", encoding="utf-8")
    return True


def resume(root: str | Path) -> bool:
    """True if the project was paused."""
    flag = home(root) / _PAUSED
    if not flag.exists():
        return False
    flag.unlink()
    return True
