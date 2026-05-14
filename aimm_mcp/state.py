"""Project state — one JSON file per project, location resolved via `session`.

`session.active_project_path()` says which file to read / write. That
file is a unified `<slug>.aimm.json` document holding the project
header, every connection, every tracked table. Tools read and write
through here.

Public surface stays narrow:

  load()          → Project | None     read the active project file
  save(project)   → Path                atomic-write the active project file
  mutate(fn)      → Project             load → fn(project) → save

`mutate` is the only safe write path. Every tool that changes
state calls it exactly once per invocation; that gives one place to
validate, atomic-write, and (optionally) fire a hook.

If no active project is set, `load` returns None and `mutate` /
`save` raise `ActiveProjectNotSelected`. Tools translate that into a
user-facing error with the bootstrap hint.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from . import paths, session
from .schemas import Connection, Project, ProjectConfig, TableMeta
from .session import ActiveProjectNotSelected


# After-mutation hook. Optional — nothing in the server wires it
# today, but the API is here so a future client can subscribe to
# "the project just changed" without touching state.py.
_after_mutation_hook: Optional[Callable[[Project], None]] = None


def set_after_mutation_hook(hook: Optional[Callable[[Project], None]]) -> None:
    global _after_mutation_hook
    _after_mutation_hook = hook


def load() -> Optional[Project]:
    """Return the active project, or None when none is selected / file missing."""
    paths.ensure_layout()
    pj = session.active_project_path()
    if pj is None or not pj.exists():
        return None
    try:
        data = json.loads(pj.read_text(encoding="utf-8"))
        return Project.model_validate(data)
    except Exception:  # noqa: BLE001 - corrupt file shouldn't crash the server
        return None


def save(project: Project) -> Path:
    """Atomic write of the active project file with a fresh `updated_at`."""
    target = session.require_active_project_path()
    return write_to(project, target)


def write_to(project: Project, target: Path) -> Path:
    """Atomic write to a specific path. Used by `init_project` to create the file
    before the active-project pointer is set."""
    project = project.model_copy(update={"updated_at": _now_iso()})
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = project.model_dump(exclude_none=False)
    fd, tmp = tempfile.mkstemp(prefix=".project.", suffix=".json.tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, target)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
    return target


def mutate(fn: Callable[[Project], Project]) -> Project:
    """Load → transform → save in one shot, then fire the hook.

    Raises `ActiveProjectNotSelected` if no active project is set —
    tool layer is expected to catch and surface the bootstrap hint.
    """
    # Eagerly resolve so the error path is the same whether the file
    # is missing because the user hasn't picked one yet, or for any
    # other reason.
    target = session.require_active_project_path()
    current = load()
    if current is None:
        # File exists per active-project pointer, but couldn't be
        # parsed. Fall back to a placeholder header so the tool
        # writing into a fresh document still works.
        current = Project(project=ProjectConfig(name="Untitled"))
    next_state = fn(current)
    write_to(next_state, target)
    if _after_mutation_hook is not None:
        try:
            _after_mutation_hook(next_state)
        except Exception:  # noqa: BLE001 - hook failure must not break the tool
            pass
    return next_state


# ---------------------------------------------------------------------------
# Convenience accessors over a Project instance
# ---------------------------------------------------------------------------


def find_table(project: Project, name: str) -> Optional[TableMeta]:
    for t in project.tables:
        if t.table_name == name:
            return t
    return None


def find_connection(project: Project, name: str) -> Optional[Connection]:
    for c in project.connections:
        if c.name == name:
            return c
    return None


def upsert_table(project: Project, meta: TableMeta) -> Project:
    """Return a new Project with `meta` replacing the table of the
    same name (or appended when new). Order preserved."""
    out: list[TableMeta] = []
    replaced = False
    for t in project.tables:
        if t.table_name == meta.table_name:
            out.append(meta)
            replaced = True
        else:
            out.append(t)
    if not replaced:
        out.append(meta)
    return project.model_copy(update={"tables": out})


def upsert_connection(project: Project, conn: Connection) -> Project:
    out: list[Connection] = []
    replaced = False
    for c in project.connections:
        if c.name == conn.name:
            out.append(conn)
            replaced = True
        else:
            out.append(c)
    if not replaced:
        out.append(conn)
    return project.model_copy(update={"connections": out})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
