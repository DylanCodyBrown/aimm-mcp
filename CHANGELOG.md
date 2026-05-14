# Changelog

## v0.2.0

Multi-project support.

- Project files are now `<slug>.aimm.json` instead of `project.json`,
  so a folder can hold many projects (a team repo of models).
- New session state at `~/Documents/AIMM/state.json` tracks the
  projects folder + which file is active. Survives across sessions.
- Four new tools for the bootstrap flow:
  - `aimm_set_projects_folder` — point at any folder of `.aimm.json`
    files (defaults to `~/Documents/AIMM/`).
  - `aimm_list_projects` — enumerate `.aimm.json` files with name +
    `updated_at`.
  - `aimm_set_active_project` — pick one as active.
  - `aimm_show_active_project` — inspect the current pointer.
- `aimm_init_project` now writes `<slug>.aimm.json` (slug derived
  from `name`) into the current folder and sets it active.
- Every project-touching tool error-traps with **"project file not
  selected"** plus a bootstrap hint until an active project is set.
- Tool count: 13 → 17.

## v0.1.0

Initial release.

- Local MCP server, distributed via `uvx aimm-mcp`.
- Single source of truth at `~/Documents/AIMM/project.json` holding
  project header, connections, and tracked tables.
- 13 tools (`aimm_*`): init, read_context, upsert_connection,
  list_system_dsns, browse_connection, refresh_columns, update_table,
  set_primary_key, add_relationship, add_upstream,
  scan_folder_for_joins, show_diagnostics_log, get_pending_changes.
- Three engines via pyodbc: Trino, SQL Server, Databricks. Per-engine
  identifier quoting + information_schema templates.
- sqlglot-driven JOIN extraction with multi-dialect fallback.
- ODBC query diagnostics written to `~/Documents/AIMM/diagnostics.log`
  with 256KB rotation.
- Bundled Claude skill in `skills/aimm-scaffold/SKILL.md`.
- CI matrix on macOS / Linux / Windows × Python 3.11 / 3.12.
