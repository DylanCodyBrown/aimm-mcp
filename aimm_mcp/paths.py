"""Filesystem layout for the local AIMM project.

Single source of truth on disk: `~/Documents/AIMM/project.json`.
Everything else either lives in memory (XML / markdown renderings of
the project) or is a side-file that isn't project state
(discovered_joins.json — scan candidates; diagnostics.log — append-log):

    ~/Documents/AIMM/
    ├── project.json             single source of truth
    ├── discovered_joins.json    candidates from a folder scan (separate)
    └── diagnostics.log          ODBC query append-log (separate)

No derived snapshots on disk. Earlier versions wrote
model.mmd / model_lineage.mmd / lineage.json / relationships.json /
joins.json / project_context.xml; those have been removed and are
deleted on activation when found.

Single-project: one model per machine.
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
    """Create the AIMM folder if it doesn't exist. Idempotent — safe
    to call on every tool invocation."""
    aimm_root().mkdir(parents=True, exist_ok=True)


def is_initialized() -> bool:
    return project_path().exists()


# ---------------------------------------------------------------------------
# Legacy cleanup
# ---------------------------------------------------------------------------


# Derived artefacts older versions wrote. Removed on activation so an
# existing install comes clean after upgrading. Idempotent: once a
# user is on the new layout, this is a no-op.
_LEGACY_DERIVED_FILES = (
    "model.mmd",
    "model_lineage.mmd",
    "lineage.json",
    "relationships.json",
    "joins.json",
    "project_context.xml",
)


def purge_legacy_derived_files() -> None:
    root = aimm_root()
    for name in _LEGACY_DERIVED_FILES:
        target = root / name
        try:
            target.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
    # Pre-v0.2 per-file storage layout — same one-shot migration the
    # state loader already runs, but the empty dirs can linger if all
    # the JSONs were deleted manually. Drop them when empty.
    for sub in ("tables", "connections"):
        d = root / sub
        if d.is_dir():
            try:
                # rmdir() is no-op-safe via try/except — only succeeds
                # when empty, which is the only case we want.
                next(d.iterdir())
            except StopIteration:
                try:
                    d.rmdir()
                except OSError:
                    pass
            except Exception:  # noqa: BLE001
                pass
