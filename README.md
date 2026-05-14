# aimm-mcp

Local **Model Context Protocol** server for the AI Model Manager.
Captures SQL data-model metadata as **one JSON file per project**
(`<slug>.aimm.json`) and exposes it to Claude Code (or any MCP
client) over stdio.

Fork of the [AIMM VS Code extension](https://github.com/DylanCodyBrown/ODBC_AI_Workbench),
rebuilt in Python with no UI: just tools the agent calls. Both the
VS Code extension and this server read/write the same project-file
format — share a project by committing one `.aimm.json` to your
repo.

## Why this exists

The VS Code extension lives inside an editor. This fork lets you
skip the editor entirely — install once with `claude mcp add`, and
any Claude session on the machine sees the same models.

## Install

One line. Claude Code spawns the server via `uvx` (uv's npx) — no
prior install, no setup.

```bash
claude mcp add aimm --scope user -- uvx aimm-mcp
```

First connection downloads the package (a few seconds). Subsequent
connections are cache-served.

For testing from a local checkout before PyPI, see
[`LOCAL_INSTALL.md`](LOCAL_INSTALL.md).

## Where state lives

Two concepts: **machine-local sidecars** (always at `~/Documents/AIMM/`)
and **project files** (anywhere you point them, default the same folder).

```
~/Documents/AIMM/                    machine-local, never moves
├── state.json                       which folder + which active project
├── discovered_joins.json            scan output (not project state)
└── diagnostics.log                  ODBC query append-log

<projects_folder>/                   defaults to ~/Documents/AIMM/
├── customer_warehouse.aimm.json     one project
├── reporting_model.aimm.json        another project
└── …
```

A team checks `<projects_folder>` into a git repo. The agent runs
`aimm_set_projects_folder` to point at the local clone, then
`aimm_list_projects` + `aimm_set_active_project` to pick one. The
"active project" pointer survives across Claude Code sessions.

No derived snapshots on disk. Renderings (XML / markdown / raw JSON)
happen in-memory when `aimm_read_project_context` is called.

## Engines

Three engines via ODBC: `trino`, `sql_server`, `databricks`.
Connection descriptors carry a DSN name (system DSN registered at
the OS level) plus the catalog / database qualifier.

## Tools

### Session / context

The agent must select an active project before any project-touching
tool runs — these tools handle that bootstrap.

- **`aimm_set_projects_folder`** — point the server at a folder of
  `.aimm.json` files (defaults to `~/Documents/AIMM/`). Use to
  switch to a team repo of shared projects. Clears the active
  pointer.
- **`aimm_list_projects`** — enumerate `.aimm.json` files in the
  current folder with their internal project name + `updated_at`.
- **`aimm_set_active_project`** — pick one as active. Subsequent
  tool calls read and write that file.
- **`aimm_show_active_project`** — report the current pointer state
  (folder + active file + on-disk status).

### Project + context

- **`aimm_init_project`** — create a new `<slug>.aimm.json` (slug
  derived from `name`) in the current folder, set it as active.
- **`aimm_read_project_context`** — return the entire active
  project. Formats: `xml` (default), `markdown`, `json` (raw bytes
  of the active file).

### Connections + live catalog

- **`aimm_upsert_connection`** — create / update a connection
  descriptor. Validates Trino catalog requirement.
- **`aimm_list_system_dsns`** — pyodbc.dataSources() wrapper for
  discovery before upsert.
- **`aimm_browse_connection`** — drill into schemas / tables /
  columns on a live connection. Optional case-insensitive search
  filter.
- **`aimm_refresh_columns`** — re-fetch column shapes from
  information_schema and merge back into the active project
  (preserves user-edited PK / FK / description flags).

### Table mutations

- **`aimm_update_table`** — patch any non-identity field on a
  tracked table. Creates on first patch.
- **`aimm_set_primary_key`** — atomically set primary_keys + flip
  is_primary_key on matching columns.
- **`aimm_add_relationship`** — append an FK edge (idempotent on
  duplicates, composite keys supported).
- **`aimm_add_upstream`** — append a lineage edge.

### Folder scan for joins

- **`aimm_scan_folder_for_joins`** — walk a local folder of `.sql`
  files, extract JOIN clauses via sqlglot (multi-dialect fallback:
  tsql → spark → none), persist canonical edges to
  `~/Documents/AIMM/discovered_joins.json`. Works without an active
  project.

### Diagnostics

- **`aimm_show_diagnostics_log`** — tail of `diagnostics.log` where
  every ODBC query is recorded.

### Pending changes

- **`aimm_get_pending_changes`** — per-tracked-table diff between
  authored columns and the live `information_schema` shape.

## Why ODBC?

Every warehouse this targets exposes an ODBC driver. We never run
user SQL — only `information_schema` reads for column / table /
schema metadata. Drivers stay read-only at the credential level.

## Development

```bash
uv sync --dev
uv run python -m aimm_mcp        # starts the MCP stdio server
uv run pytest -q                 # tests
```

## License

MIT.
