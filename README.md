# aimm-mcp

Local **Model Context Protocol** server for the AI Model Manager. Captures
SQL data-model metadata under `~/Documents/AIMM/` and exposes it to Claude
Code (or any MCP client) over stdio.

Fork of the [AIMM VS Code extension](https://github.com/DylanCodyBrown/ODBC_AI_Workbench),
rebuilt in Python with no UI: just tools the agent calls.

## Why this exists

The VS Code extension lives inside an editor. This fork lets you skip
the editor entirely — install once with `claude mcp add`, and any
Claude session on the machine sees the same model.

## Install

One line. Claude Code spawns the server via `uvx` (uv's npx) — no
prior install, no setup.

```bash
claude mcp add aimm --scope user -- uvx aimm-mcp
```

First connection downloads the package (a few seconds). Subsequent
connections are cache-served. Server lives under `~/Documents/AIMM/`
so every project on the machine shares one model.

## What lives under `~/Documents/AIMM/`

One canonical document holds the project, every connection, and every
tracked table. Share the project with a teammate by handing them
`project.json`.

```
~/Documents/AIMM/
├── project.json             ← THE source of truth (project + connections + tables)
├── discovered_joins.json    candidates from `aimm_scan_folder_for_joins`
└── diagnostics.log          append-log of every ODBC query the server ran
```

No derived snapshots on disk. Renderings (XML / markdown / raw JSON)
happen in-memory when `aimm_read_project_context` is called.

Pre-v0.3 layouts (`aimm.json` + `tables/*.json` + `connections/*.json`,
or derived mermaid / json snapshots from v0.2) are migrated /
cleaned up on first load.

## Engines

Three engines via ODBC: `trino`, `sql_server`, `databricks`. Connection
descriptors carry a DSN name (system DSN registered at the OS level)
plus the catalog / database qualifier.

## Tools

Every tool reads and writes `project.json` exclusively. There is no
separate cache, no derived snapshots, no auto-regenerate. The on-disk
file is the model.

### Project + context

- **`aimm_init_project`** — bootstrap `~/Documents/AIMM/project.json`.
  Idempotent; arguments patch the header on re-runs.
- **`aimm_read_project_context`** — return the entire project. Formats:
  `xml` (default; agent-friendly tag-delimited), `markdown` (prose
  digest), or `json` (raw contents of `project.json`, same shape the
  server writes on every mutation).

### Connections + live catalog

- **`aimm_upsert_connection`** — create / update a connection
  descriptor. Validates Trino catalog requirement.
- **`aimm_list_system_dsns`** — pyodbc.dataSources() wrapper for
  discovery before upsert.
- **`aimm_browse_connection`** — drill into schemas / tables / columns
  on a live connection. Optional case-insensitive search filter.
- **`aimm_refresh_columns`** — re-fetch column shapes from
  information_schema and merge back into project.json (preserves
  user-edited PK / FK / description flags).

### Table mutations

- **`aimm_update_table`** — patch any non-identity field on a tracked
  table. Creates on first patch.
- **`aimm_set_primary_key`** — atomically set primary_keys + flip
  is_primary_key on matching columns.
- **`aimm_add_relationship`** — append an FK edge (idempotent on
  duplicates, composite keys supported).
- **`aimm_add_upstream`** — append a lineage edge.

### Folder scan for joins

- **`aimm_scan_folder_for_joins`** — walk a local folder of `.sql`
  files, extract JOIN clauses via sqlglot (multi-dialect fallback:
  tsql → spark → none), persist canonical edges to
  `discovered_joins.json`.

### Diagnostics

- **`aimm_show_diagnostics_log`** — tail of `diagnostics.log` where
  every ODBC query is recorded.

### Pending changes

- **`aimm_get_pending_changes`** — per-tracked-table diff between
  authored columns (in `project.json`) and the live
  `information_schema` shape. Tells the agent "what would I deploy if
  I promoted these views right now."

## Why ODBC?

Every warehouse this targets exposes an ODBC driver. We never run user
SQL — only `information_schema` reads for column / table / schema
metadata. Drivers stay read-only at the credential level.

## Development

```bash
uv sync
uv run python -m aimm_mcp        # starts the MCP stdio server
uv run pytest                    # tests
```

## License

MIT.
