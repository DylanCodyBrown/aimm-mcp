"""Filesystem layout for the local AIMM project.

The extension version lives inside a VS Code workspace. The MCP fork
lives at a fixed location under the user's home so any Claude session
(or other MCP client) finds the same project without configuration:

    ~/Documents/AIMM/
    ├── aimm.json                project config
    ├── tables/<name>.json       per-table metadata
    ├── connections/<name>.json  per-connection metadata
    ├── model.mmd                generated ER diagram
    ├── model_lineage.mmd        generated lineage flowchart
    ├── lineage.json             flat upstream→downstream edges
    ├── relationships.json       flat FK edges
    ├── joins.json               project-tracked joins
    ├── discovered_joins.json    candidates from a folder scan
    ├── project_context.xml      agent-facing context dump
    ├── diagnostics.log          ODBC query log
    └── .sync_cache/             reserved (unused for now)

Single-project: one model per machine. No multi-project routing, no
--project flag.
"""

from __future__ import annotations

from pathlib import Path


AIMM_DIR_NAME = "AIMM"


def aimm_root() -> Path:
    """Resolve the AIMM directory under the user's Documents folder.

    Cross-platform: `Path.home() / 'Documents' / 'AIMM'` on Windows,
    macOS, and Linux. Most distros either honour the convention or have
    the folder linked. We don't try XDG_DOCUMENTS_DIR — single answer
    everywhere keeps the install one-liner predictable.
    """
    return Path.home() / "Documents" / AIMM_DIR_NAME


def project_config_path() -> Path:
    return aimm_root() / "aimm.json"


def tables_dir() -> Path:
    return aimm_root() / "tables"


def table_json_path(name: str) -> Path:
    return tables_dir() / f"{name}.json"


def connections_dir() -> Path:
    return aimm_root() / "connections"


def connection_json_path(name: str) -> Path:
    return connections_dir() / f"{name}.json"


def mermaid_er_path() -> Path:
    return aimm_root() / "model.mmd"


def mermaid_lineage_path() -> Path:
    return aimm_root() / "model_lineage.mmd"


def lineage_json_path() -> Path:
    return aimm_root() / "lineage.json"


def relationships_json_path() -> Path:
    return aimm_root() / "relationships.json"


def joins_json_path() -> Path:
    return aimm_root() / "joins.json"


def discovered_joins_path() -> Path:
    return aimm_root() / "discovered_joins.json"


def context_xml_path() -> Path:
    return aimm_root() / "project_context.xml"


def diagnostics_log_path() -> Path:
    return aimm_root() / "diagnostics.log"


def ensure_layout() -> None:
    """Create the AIMM folder skeleton if it doesn't exist. Idempotent —
    safe to call on every tool invocation."""
    root = aimm_root()
    root.mkdir(parents=True, exist_ok=True)
    tables_dir().mkdir(exist_ok=True)
    connections_dir().mkdir(exist_ok=True)


def is_initialized() -> bool:
    return project_config_path().exists()
