# Changelog

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
