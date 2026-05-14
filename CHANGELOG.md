# Changelog

## v0.3.0

Semantic-context layer. The structural layer (tables, columns, FKs,
lineage) tells the agent **what's there**; this release adds the
fields that tell it **what it means**.

### Schema additions

Every new field is optional with a sensible default. v0.2 files
still parse unchanged.

- **Per-table grain.** `grain: string?` (≤240). One-line answer to
  "what is one row in this table?". Anchors fact-vs-dim reasoning.
- **Per-table pitfalls.** `pitfalls: string[]` (each ≤240). Short
  "don't do this" rules — "Do not join on customer_email; use
  customer_id."
- **Per-table aliases.** `aliases: string[]`. Other names this table
  goes by ("transactions" = "orders").
- **Per-table owner.** `owner: string?` (≤240). Free-text contact.
- **Per-table refresh cadence.** `refresh_cadence: unknown |
  realtime | minutes | hourly | daily | weekly | monthly | adhoc` +
  optional `refresh_notes`.
- **Per-table SCD metadata.** `scd: { type, valid_from?, valid_to?,
  is_current_flag? }` for history-tracked tables (scd1, scd2,
  snapshot).
- **Per-table operational stamps.** `row_count_last_run: int?`,
  `last_run_at: string?` — auto-set by `aimm_refresh_columns` so the
  agent knows freshness without a side query.
- **Per-column classification.** `classification: unspecified |
  public | internal | pii | phi | restricted`. Lets the agent
  self-guardrail.
- **Per-column quality notes.** `quality_notes: string?` (≤240).
  "30% null pre-2023", etc.
- **Per-column computed flag + expression.** `computed: boolean`,
  `expression: string?` (≤1 000). Derived columns carry their
  formula.
- **Per-column example values.** `example_values: string[]`.
- **Project glossary.** `glossary: { term, definition }[]`. Domain
  dictionary.
- **Project measures.** `measures: { name, definition, formula?,
  owner? }[]`. KPI definitions.
- **Project conventions.** `conventions: string` (≤8 000). Free-text
  naming / typing rules.

### Tools

Six new dedicated mutation tools (single-purpose for agent
discoverability):

- `aimm_set_table_grain` — set the per-table grain.
- `aimm_add_pitfall` — append-with-dedupe to pitfalls.
- `aimm_set_column_classification` — flip a column's sensitivity tag.
- `aimm_add_glossary_term` — upsert by term.
- `aimm_add_measure` — upsert by name.
- `aimm_update_project_config` — generic patch for the project
  header (description, conventions, dialect, default_connection,
  modeling_paradigm, tags).

`aimm_update_table` accepts every new semantic field as a patch key,
so an agent can also batch-update via the generic path. Tool count:
17 → 23.

### Context rendering

`format_context.format_project_context` emits every new field when
set, in both XML (default) and markdown. Empty / default values are
still omitted so the dump stays dense.

The `<aimm_schema>` preamble was updated to document the new
vocabulary — agents that consume the XML get the new fields
explained inline.

### Internal

- `aimm_refresh_columns` now stamps `last_run_at` on every refreshed
  table.
- All user-edited per-column hints (description, classification,
  quality_notes, computed, expression, example_values) are
  preserved across a refresh.

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
