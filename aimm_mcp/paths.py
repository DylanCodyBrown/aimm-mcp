"""Filesystem layout under `~/Documents/AIMM/`.

    ~/Documents/AIMM/
    ├── state.json               which folder + which active project
    ├── <slug>.aimm.json         a project file (zero or more)
    ├── discovered_joins.json    candidates from a folder scan
    └── diagnostics.log          ODBC query append-log

`projects_folder` defaults to this directory, but can be repointed at
any folder on disk (typically a team repo of `.aimm.json` files) via
`aimm_set_projects_folder`. `state.json`, `discovered_joins.json`, and
`diagnostics.log` stay here regardless — they're machine-local
sidecars, not project state.
"""

from __future__ import annotations

from pathlib import Path


AIMM_DIR_NAME = "AIMM"


def aimm_root() -> Path:
    """Resolve the AIMM directory under the user's Documents folder."""
    return Path.home() / "Documents" / AIMM_DIR_NAME


def state_file_path() -> Path:
    """Persisted session pointer (projects_folder + active_project_file)."""
    return aimm_root() / "state.json"


def discovered_joins_path() -> Path:
    return aimm_root() / "discovered_joins.json"


def diagnostics_log_path() -> Path:
    return aimm_root() / "diagnostics.log"


def ensure_layout() -> None:
    """Create the AIMM folder if it doesn't exist. Idempotent."""
    aimm_root().mkdir(parents=True, exist_ok=True)
