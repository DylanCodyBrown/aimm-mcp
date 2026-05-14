"""Filesystem layout under `~/Documents/AIMM/`.

    ~/Documents/AIMM/
    ├── project.json             single source of truth
    ├── discovered_joins.json    candidates from a folder scan (separate)
    └── diagnostics.log          ODBC query append-log (separate)

Single project per machine. Single file owns the model. Other two
files are sidecars — not project state.
"""

from __future__ import annotations

from pathlib import Path


AIMM_DIR_NAME = "AIMM"


def aimm_root() -> Path:
    """Resolve the AIMM directory under the user's Documents folder."""
    return Path.home() / "Documents" / AIMM_DIR_NAME


def project_path() -> Path:
    """The single canonical file. Holds project + connections + tables."""
    return aimm_root() / "project.json"


def discovered_joins_path() -> Path:
    return aimm_root() / "discovered_joins.json"


def diagnostics_log_path() -> Path:
    return aimm_root() / "diagnostics.log"


def ensure_layout() -> None:
    """Create the AIMM folder if it doesn't exist. Idempotent."""
    aimm_root().mkdir(parents=True, exist_ok=True)


def is_initialized() -> bool:
    return project_path().exists()
