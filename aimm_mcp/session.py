"""Session state — which projects folder + which active project file.

Project state itself lives in `<projects_folder>/<active_project_file>`
(a `<slug>.aimm.json` document). Where that folder is, and which file
inside it is currently active, is the session's responsibility.

Lives at `~/Documents/AIMM/state.json`:

    {
      "schema_version": 1,
      "projects_folder": "/abs/path/to/folder",
      "active_project_file": "customer_warehouse.aimm.json"
    }

Defaults: `projects_folder = ~/Documents/AIMM/`, `active_project_file =
null`. The agent must explicitly set the active project before any
project-touching tool will run — `aimm_list_projects` + `aimm_set_active_project`,
or `aimm_init_project` for a new one. This is intentional: one
machine can hold many project files (a team repo of models), and we
don't want a default that silently picks the wrong one.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from . import paths


PROJECT_FILE_SUFFIX = ".aimm.json"


class SessionState(BaseModel):
    """Persisted session pointer. Owned by state.json."""

    model_config = ConfigDict(extra="ignore")

    schema_version: int = 1
    projects_folder: Optional[str] = None
    active_project_file: Optional[str] = None


class ActiveProjectNotSelected(Exception):
    """Raised by `require_active_project_path` when no active project is set.

    Carries the same hint the tool layer surfaces to the agent so every
    error trap reads consistently.
    """

    def __init__(self, message: str = "project file not selected") -> None:
        super().__init__(message)
        self.hint = (
            "Call aimm_list_projects to see what's in the current projects "
            "folder, then aimm_set_active_project. To create a new project, "
            "call aimm_init_project. To point at a different folder of "
            "projects (e.g. a team repo), call aimm_set_projects_folder first."
        )


# ---------------------------------------------------------------------------
# State file I/O
# ---------------------------------------------------------------------------


def load_session() -> SessionState:
    """Read state.json, or return defaults when it doesn't exist / is corrupt."""
    paths.ensure_layout()
    sf = paths.state_file_path()
    if not sf.exists():
        return SessionState()
    try:
        data = json.loads(sf.read_text(encoding="utf-8"))
        return SessionState.model_validate(data)
    except Exception:  # noqa: BLE001 - corrupt state.json shouldn't brick the server
        return SessionState()


def save_session(session: SessionState) -> Path:
    """Atomic write of state.json."""
    target = paths.state_file_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".state.", suffix=".json.tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(session.model_dump(exclude_none=False), fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, target)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
    return target


# ---------------------------------------------------------------------------
# Folder + active-file resolution
# ---------------------------------------------------------------------------


def projects_folder() -> Path:
    """The folder of `.aimm.json` files. Defaults to `~/Documents/AIMM/`."""
    s = load_session()
    if s.projects_folder:
        return Path(s.projects_folder).expanduser()
    return paths.aimm_root()


def active_project_path() -> Optional[Path]:
    """Resolved path of the active project file, or None if none is set."""
    s = load_session()
    if not s.active_project_file:
        return None
    return projects_folder() / s.active_project_file


def require_active_project_path() -> Path:
    """Same, but raises ActiveProjectNotSelected when not set.

    Used by every write path. The tool layer catches and converts to a
    user-facing error message with the hint.
    """
    p = active_project_path()
    if p is None:
        raise ActiveProjectNotSelected()
    return p


# ---------------------------------------------------------------------------
# Mutators (the tools call these)
# ---------------------------------------------------------------------------


def set_projects_folder(path: Path) -> SessionState:
    """Validate + persist. The folder must already exist on disk."""
    p = path.expanduser().resolve()
    if not p.exists() or not p.is_dir():
        raise FileNotFoundError(f"projects folder not found: {p}")
    current = load_session()
    next_state = current.model_copy(update={
        "projects_folder": str(p),
        # Folder change invalidates the active file — its name might
        # exist in the new folder too, but we don't assume.
        "active_project_file": None,
    })
    save_session(next_state)
    return next_state


def set_active_project(filename: str) -> SessionState:
    """Validate that the file exists in the current folder, then persist."""
    if not filename:
        raise ValueError("filename is required")
    full = projects_folder() / filename
    if not full.exists() or not full.is_file():
        raise FileNotFoundError(f"project file not found: {full}")
    current = load_session()
    next_state = current.model_copy(update={"active_project_file": filename})
    save_session(next_state)
    return next_state


def clear_active_project() -> SessionState:
    """Drop the active-project pointer without touching the folder."""
    current = load_session()
    next_state = current.model_copy(update={"active_project_file": None})
    save_session(next_state)
    return next_state


# ---------------------------------------------------------------------------
# Filename convention
# ---------------------------------------------------------------------------


_SLUG_NON_ALNUM = re.compile(r"[^a-zA-Z0-9]+")


def slugify(name: str) -> str:
    """`'Customer Warehouse'` → `'customer_warehouse'`.

    Non-alnum runs collapse to `_`; trims leading/trailing `_`; lower.
    Empty result falls back to `untitled` so we always have a filename.
    """
    s = _SLUG_NON_ALNUM.sub("_", name).strip("_").lower()
    return s or "untitled"


def filename_for(name: str) -> str:
    """Slug + `.aimm.json` — the canonical filename for a named project."""
    return slugify(name) + PROJECT_FILE_SUFFIX


def list_project_files() -> list[Path]:
    """Every `*.aimm.json` file in the current folder (alphabetical)."""
    folder = projects_folder()
    if not folder.exists():
        return []
    return sorted(folder.glob(f"*{PROJECT_FILE_SUFFIX}"))
