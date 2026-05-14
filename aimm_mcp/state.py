"""Unified project state — one JSON file owns everything.

The single source of truth is `~/Documents/AIMM/project.json`. It
holds the project header, every connection, every tracked table —
all the state the agent reads or mutates. Derived artefacts (mermaid
diagrams, lineage.json, relationships.json, joins.json,
project_context.xml) are written on the side; they're snapshots, not
state.

Public API stays narrow:

  load()              read project.json (auto-migrates on first run)
  save(project)       atomic-write project.json
  mutate(fn)          load → fn(project) → save in one transaction;
                       fires the after-mutation hook automatically
  set_after_mutation_hook(cb)
                      called with the saved project after every mutate.
                      The diagrams tool installs the auto-regenerate
                      hook here so every write rebuilds the derived
                      artefacts in real time.

Backwards-compat migration: when the old per-file layout is found
(aimm.json + tables/*.json + connections/*.json), `load` consolidates
it into project.json on first read and removes the old files. One-way,
idempotent — re-running is a no-op.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from . import paths
from .schemas import Connection, Project, ProjectConfig, TableMeta


# After-mutation hook: called with the saved Project after every
# successful mutate(). The diagrams tool installs the
# auto-regenerate callback here so derived artefacts stay in sync.
_after_mutation_hook: Optional[Callable[[Project], None]] = None


def set_after_mutation_hook(hook: Optional[Callable[[Project], None]]) -> None:
    global _after_mutation_hook
    _after_mutation_hook = hook


def load() -> Optional[Project]:
    """Return the current project, or None when not yet initialised.

    Runs the legacy-layout migration on first call if the old per-file
    layout is found. Migration is idempotent and one-way."""
    paths.ensure_layout()
    pj_path = paths.aimm_root() / "project.json"

    if pj_path.exists():
        return _read_unified(pj_path)

    # Legacy migration: build a Project from the old per-file layout
    # and persist it as project.json. After this runs once, the old
    # files have been folded in and we can drop them.
    migrated = _try_migrate_legacy()
    if migrated is not None:
        save(migrated)
        _delete_legacy_files()
        return migrated

    return None


def save(project: Project) -> Path:
    """Atomic write of the unified document, with a fresh updated_at."""
    project = project.model_copy(update={"updated_at": _now_iso()})
    target = paths.aimm_root() / "project.json"
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
    """Load → transform → save in one shot, then fire the
    after-mutation hook. Tools that mutate state call this exactly once
    per invocation so the auto-regenerate of derived artefacts (mermaid,
    lineage.json, etc.) fires in real time.

    `fn` receives the current project (creating an empty one if no
    project.json exists yet — useful for create-on-patch paths) and
    returns the updated project to persist."""
    current = load()
    if current is None:
        # Caller is mutating before init. Bootstrap with a placeholder
        # name; init_project overrides this. The alternative — raising
        # here — would force every write-path to error-check, which
        # makes the surface more brittle for agents.
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
# Helpers: convenience accessors over the unified document
# ---------------------------------------------------------------------------


def find_table(project: Project, name: str) -> Optional[TableMeta]:
    for t in project.tables:
        if t.table_name == name:
            return t
    return None


def find_table_lower(project: Project, name: str) -> Optional[TableMeta]:
    lname = name.lower()
    for t in project.tables:
        if t.table_name.lower() == lname:
            return t
    return None


def find_connection(project: Project, name: str) -> Optional[Connection]:
    for c in project.connections:
        if c.name == name:
            return c
    return None


def upsert_table(project: Project, meta: TableMeta) -> Project:
    """Return a new Project with `meta` replacing the table of the same
    name (or appended when new)."""
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


# ---------------------------------------------------------------------------
# I/O details
# ---------------------------------------------------------------------------


def _read_unified(path: Path) -> Optional[Project]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Project.model_validate(data)
    except Exception:  # noqa: BLE001 - corrupt file shouldn't crash the server
        return None


def _try_migrate_legacy() -> Optional[Project]:
    """Build a Project from the old per-file layout if any of the
    legacy files exist. Returns None when no legacy state is present."""
    cfg_path = paths.aimm_root() / "aimm.json"
    tables_dir = paths.aimm_root() / "tables"
    conns_dir = paths.aimm_root() / "connections"

    # Only consider it legacy state when there are actual files to
    # migrate. `paths.ensure_layout()` creates empty tables/ and
    # connections/ dirs eagerly, so directory existence alone isn't
    # a signal.
    def _has_json_files(d: Path) -> bool:
        if not d.is_dir():
            return False
        return any(p.suffix == ".json" and not p.name.startswith(".") for p in d.iterdir())

    has_legacy = cfg_path.exists() or _has_json_files(tables_dir) or _has_json_files(conns_dir)
    if not has_legacy:
        return None

    cfg: ProjectConfig
    if cfg_path.exists():
        try:
            raw = json.loads(cfg_path.read_text(encoding="utf-8"))
            cfg = ProjectConfig.model_validate(raw)
        except Exception:  # noqa: BLE001
            cfg = ProjectConfig(name="Migrated")
    else:
        cfg = ProjectConfig(name="Migrated")

    tables: list[TableMeta] = []
    if tables_dir.exists():
        for p in sorted(tables_dir.glob("*.json")):
            if p.name.startswith("."):
                continue
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                tables.append(TableMeta.model_validate(raw))
            except Exception:  # noqa: BLE001
                continue

    conns: list[Connection] = []
    if conns_dir.exists():
        for p in sorted(conns_dir.glob("*.json")):
            if p.name.startswith("."):
                continue
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                conns.append(Connection.model_validate(raw))
            except Exception:  # noqa: BLE001
                continue

    return Project(project=cfg, connections=conns, tables=tables)


def _delete_legacy_files() -> None:
    """Drop the old per-file artefacts now that project.json owns
    everything. One-way: the migration is idempotent on re-runs
    because we only get here after writing project.json."""
    cfg = paths.aimm_root() / "aimm.json"
    try:
        cfg.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass
    for d in (paths.aimm_root() / "tables", paths.aimm_root() / "connections"):
        if d.exists():
            try:
                shutil.rmtree(d)
            except Exception:  # noqa: BLE001
                pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
