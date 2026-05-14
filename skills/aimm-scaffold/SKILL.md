---
name: aimm-scaffold
description: Scaffold or extend an AIMM (AI Model Manager) data model using the aimm-mcp tools. Use when the user wants to pick a project, set up a new model, add a connection, document tables, declare relationships or lineage, capture grain / pitfalls / glossary / measures, scan a folder of SQL for joins, or inspect the current project state. Don't use for unrelated SQL work.
allowed-tools: aimm_set_projects_folder, aimm_list_projects, aimm_set_active_project, aimm_show_active_project, aimm_init_project, aimm_read_project_context, aimm_upsert_connection, aimm_list_system_dsns, aimm_browse_connection, aimm_refresh_columns, aimm_update_table, aimm_set_primary_key, aimm_add_relationship, aimm_add_upstream, aimm_set_table_grain, aimm_add_pitfall, aimm_set_column_classification, aimm_add_glossary_term, aimm_add_measure, aimm_update_project_config, aimm_scan_folder_for_joins, aimm_show_diagnostics_log, aimm_get_pending_changes
---

# AIMM scaffold

`aimm-mcp` is a local MCP server that stores SQL-data-model metadata
in **one JSON file per project**: `<slug>.aimm.json`. Project files
live in a folder of the user's choice (defaults to
`~/Documents/AIMM/`), so a team can keep them in a shared repo and
hand-edit / diff / PR the same way they do any other code artefact.

## Where state lives

```
~/Documents/AIMM/                   ← machine-local, never moves
├── state.json                        which folder + which active file
├── discovered_joins.json             scan output (not project state)
└── diagnostics.log                   ODBC query append-log

<projects_folder>/                  ← configurable; defaults to ~/Documents/AIMM/
├── customer_warehouse.aimm.json      one project
├── reporting_model.aimm.json         another project
└── …
```

Every project-touching write tool reads → mutates → atomic-writes the
**active** project file.

## Session bootstrap — required before any project tool runs

Tools that read or write a project will error with **"project file
not selected"** until an active project is set. Don't try to work
around this: ask the user which project they want.

1. **Inspect the current pointer.**
   `aimm_show_active_project()` returns `projects_folder` +
   `active_project_file` + status. Call this first.

2. **If a different projects folder is needed**, ask the user where
   their `.aimm.json` files live (typically a team repo). Then:
   `aimm_set_projects_folder({path: "/abs/path/to/folder"})`.
   This also clears the active pointer.

3. **See what's available.** `aimm_list_projects()` returns the
   filename, internal project name, and `updated_at` for each
   `*.aimm.json` in the folder.

4. **Pick one.**
   `aimm_set_active_project({filename: "customer_warehouse.aimm.json"})`.
   Subsequent tool calls now read and write that file.

5. **Or create a new one.**
   `aimm_init_project({name: "Customer Warehouse", description?, dialect?})`.
   Writes `customer_warehouse.aimm.json` (slug from `name`) into the
   current folder and sets it active. If the file already exists,
   call `aimm_set_active_project` instead.

After step 4 or 5, call `aimm_read_project_context` once to load the
project into your context, then proceed with normal work.

## Authoring sequence (once active project is set)

1. **Add a connection.** First confirm a DSN exists on the machine:
   `aimm_list_system_dsns()`. Then `aimm_upsert_connection({name,
   engine, dsn, catalog})`. Engines: `trino`, `sql_server`,
   `databricks`. Trino requires a `catalog`.

2. **Browse the live catalog.** Ask the user which schemas matter
   before listing — `aimm_browse_connection({connection})` returns
   *every* schema, can be long. Drill: `{connection, schema}` lists
   tables; `{connection, schema, table}` lists columns. `search` is a
   case-insensitive substring filter at the current level.

3. **Track tables.** For each table the user picks:
   `aimm_update_table({name, patch:{connection, staging_target:"<schema>.<table>", description}})`.
   `staging_target` is what makes column resolution work — without it
   the server can't fetch live column shapes.

4. **Pull column shapes.** `aimm_refresh_columns()` — fetches every
   tracked table's columns from `information_schema` and merges into
   the project file (preserves user-edited PK / FK / description
   flags). `force: true` bypasses the 5-min catalog cache.

5. **Set primary keys.** `aimm_set_primary_key({table, columns})`.
   Inference, in order of confidence:
   - column literally named `id` in a singular-named table → PK
   - `<table>_id` in the same table → PK
   - composite of `<other>_id` columns on link tables → composite PK
   - else **ask**

6. **Add relationships.** `aimm_add_relationship({from, to,
   from_columns, to_columns, cardinality, description?})`.
   Cardinality defaults reasonably: `one_to_many` when the child holds
   the FK; `one_to_one` only with a unique constraint on the FK
   column; `many_to_many` only on link tables.

7. **Add lineage (if the user knows).** `aimm_add_upstream({from, ref,
   description?})`. `ref` can be a tracked table's name or a free-form
   external identifier (`raw.public.orders`). Don't fabricate.

8. **Capture the semantic layer.** This is where the project becomes
   *self-explanatory* to the next agent that opens it. Whenever the
   user tells you something a structural read wouldn't reveal, write
   it down with the dedicated tool:

   - **Grain.** `aimm_set_table_grain({table, grain})`. One short
     line per table — "one row per order line item". Anchors every
     fact-vs-dim conversation.
   - **Pitfalls.** `aimm_add_pitfall({table, message})`. Short "don't
     do this" rules — "Don't join on customer_email; use customer_id
     (email is reused after anonymisation)." Dedupes exact duplicates.
   - **Column sensitivity.** `aimm_set_column_classification({table,
     column, classification})`. `pii` / `phi` / `restricted` /
     `internal` / `public`. The agent self-guardrails on these.
   - **Glossary.** `aimm_add_glossary_term({term, definition})`.
     Domain dictionary — "active customer = at least one paid order
     in the trailing 90 days". Upsert by term.
   - **Measures.** `aimm_add_measure({name, definition, formula?,
     owner?})`. KPI definitions. Always capture the **formula** so
     the next agent quotes it instead of inventing one.
   - **Project header / conventions.** `aimm_update_project_config({patch})`.
     Use for `description`, `conventions` ("all booleans end in
     _flag, all dates UTC"), `dialect`, `default_connection`,
     `modeling_paradigm`, `tags`.
   - **Everything else.** `aimm_update_table({name, patch})` accepts
     every other semantic field as a patch key: `aliases`, `owner`,
     `refresh_cadence`, `refresh_notes`, `scd: {type, valid_from,
     valid_to, is_current_flag}`. Column-level: `quality_notes`,
     `computed`, `expression`, `example_values`.

   Heuristic: if the user tells you something *about* the data
   (semantics, conventions, gotchas) and not just its shape, that
   knowledge belongs in the project. Capture it the moment you hear
   it.

## Reading state

`aimm_read_project_context({format})` returns the whole project.

- `xml` (default) — tag-delimited, best for cross-referential reasoning.
- `markdown` — leaner prose digest.
- `json` — raw bytes of the active `.aimm.json` file. Use when you
  want to operate on the project structurally.

Always read once at session start (after the active project is set)
before answering data-model questions.

## Folder scan for joins

`aimm_scan_folder_for_joins({folder, dialect?, max_files?})` walks a
local directory of `.sql` files, parses each with sqlglot (multi-
dialect fallback: configured → tsql → spark → none), and writes
canonical join edges to `~/Documents/AIMM/discovered_joins.json`.
Doesn't touch the active project file. Useful for: "what tables
join to what in this repo of analytics queries?" — works without an
active project, so you can scan before scaffolding.

## Pending changes (deploy check)

`aimm_get_pending_changes({table?, force?})` — diff between authored
columns (in the active project) and the live `information_schema`
shape. Surfaces added / removed / type-changed columns per table.
Use before promoting views.

## Diagnostics

`aimm_show_diagnostics_log({max_bytes?})` returns the tail of
`~/Documents/AIMM/diagnostics.log` where every ODBC query the server
ran is recorded with timing, DSN, and result. Use when a tool returns
`connect_failed` / `query_failed` and you want the SQL.

## Hard constraints

- Never enumerate every schema/table just to "see what's there." Ask
  the user which domain matters first.
- Never invent connections, PKs, FKs, or lineage the user hasn't
  sanctioned.
- Never edit a `.aimm.json` directly. The `aimm_*` tools validate via
  pydantic and write atomically; direct edits bypass that.
- If a project-touching tool returns **"project file not selected"**,
  do **not** retry. Run the bootstrap sequence (folder → list →
  active, or init) first, with user input on which project.
- Never call `aimm_set_projects_folder` to a path the user hasn't
  named. If unsure, ask.
