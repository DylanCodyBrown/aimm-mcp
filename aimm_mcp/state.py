"""Project state — one JSON file owns everything.

`~/Documents/AIMM/project.json` is the single source of truth. It
holds the project header, every connection, every tracked table.
Tools read and write through here.

Public surface stays narrow:

  load()          → Project | None     read project.json
  save(project)   → Path                atomic-write project.json
  mutate(fn)      → Project             load → fn(project) → save

`mutate` is the only safe write path. Every tool that changes
state calls it exactly once per invocation; that gives one place to
validate, atomic-write, and (optionally) fire a hook.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from . import paths
from .schemas import Connection, Project, ProjectConfig, TableMeta


# After-mutation hook. Optional — nothing in the server wires it
# today, but the API is here so a future client can subscribe to
# "the project just changed" without touching state.py.
_after_mutation_hook: Optional[Callable[[Project], None]] = None


def set_after_mutation_hook(hook: Optional[Callable[[Project], None]]) -> None:
    global _after_mutation_hook
    _after_mutation_hook = hook


def load() -> Optional[Project]:
    """Return the current project, or None when not yet initialised."""
    paths.ensure_layout()
    pj = paths.project_path()
    if not pj.exists():
        return None
    try:
        data = json.loads(pj.read_text(encoding="utf-8"))
        return Project.model_validate(data)
    except Exception:  # noqa: BLE001 - corrupt file shouldn't crash the server
        return None


def save(project: Project) -> Path:
    """Atomic write of project.json with a fresh `updated_at`."""
    project = project.model_copy(update={"updated_at": _now_iso()})
    target = paths.project_path()
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

    `fn` receives the current project (an empty one if no
    project.json exists yet, so create-on-patch paths work without
    a special-case) and returns the project to persist.
    """
    current = load()
    if current is None:
        # Caller is mutating before init. Bootstrap with a placeholder
        # name; init_project overrides this. Raising here would force
        # every write-path to error-check, which makes the surface
        # brittle for agents.
        current = Project(project=ProjectConfig(name="Untitled"))
    next_state = fn(current)
    save(next_state)
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
