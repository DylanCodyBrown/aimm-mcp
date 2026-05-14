---
name: aimm-scaffold
description: Scaffold or extend an AIMM (AI Model Manager) data model using the aimm-mcp tools. Use when the user wants to set up a new model, add a connection, document tables, declare relationships or lineage, scan a folder of SQL for joins, or check what's currently in `~/Documents/AIMM/project.json`. Don't use for unrelated SQL work.
allowed-tools: aimm_init_project, aimm_read_project_context, aimm_upsert_connection, aimm_list_system_dsns, aimm_browse_connection, aimm_refresh_columns, aimm_update_table, aimm_set_primary_key, aimm_add_relationship, aimm_add_upstream, aimm_scan_folder_for_joins, aimm_show_diagnostics_log, aimm_get_pending_changes
---

# AIMM scaffold

`aimm-mcp` is a local MCP server that stores SQL-data-model metadata in
one file: `~/Documents/AIMM/project.json`. It does **not** execute user
SQL. Reads to `information_schema` only.

## Where state lives

```
~/Documents/AIMM/
├── project.json          ← project + connections + tables (single source of truth)
├── discovered_joins.json ← scan results from aimm_scan_folder_for_joins
└── diagnostics.log       ← every ODBC query the server ran (paste-able)
```

Every write tool reads → mutates → atomic-writes `project.json`.

## Bootstrap sequence

Run this once per project, in order. Skip steps that are already done
(check first with `aimm_read_project_context`).

1. **Initialise.** `aimm_init_project({name, description?, dialect?})`.
   Creates `project.json` if missing; otherwise patches the header.

2. **Add a connection.** First confirm a DSN exists on the machine:
   `aimm_list_system_dsns()`. Then `aimm_upsert_connection({name,
   engine, dsn, catalog})`. Engines: `trino`, `sql_server`,
   `databricks`. Trino requires a `catalog`.

3. **Browse the live catalog.** Ask the user which schemas matter
   before listing — `aimm_browse_connection({connection})` returns
   *every* schema, can be long. Drill: `{connection, schema}` lists
   tables; `{connection, schema, table}` lists columns. `search` is a
   case-insensitive substring filter at the current level.

4. **Track tables.** For each table the user picks:
   `aimm_update_table({name, patch:{connection, staging_target:"<schema>.<table>", description}})`.
   `staging_target` is what makes column resolution work — without it
   the server can't fetch live column shapes.

5. **Pull column shapes.** `aimm_refresh_columns()` — fetches every
   tracked table's columns from `information_schema` and merges into
   `project.json` (preserves user-edited PK / FK / description flags).
   `force: true` bypasses the 5-min catalog cache.

6. **Set primary keys.** `aimm_set_primary_key({table, columns})`.
   Inference, in order of confidence:
   - column literally named `id` in a singular-named table → PK
   - `<table>_id` in the same table → PK
   - composite of `<other>_id` columns on link tables → composite PK
   - else **ask**

7. **Add relationships.** `aimm_add_relationship({from, to,
   from_columns, to_columns, cardinality, description?})`.
   Cardinality defaults reasonably: `one_to_many` when the child holds
   the FK; `one_to_one` only with a unique constraint on the FK
   column; `many_to_many` only on link tables.

8. **Add lineage (if the user knows).** `aimm_add_upstream({from, ref,
   description?})`. `ref` can be a tracked table's name or a free-form
   external identifier (`raw.public.orders`). Don't fabricate.

## Reading state

`aimm_read_project_context({format})` returns the whole project.

- `xml` (default) — tag-delimited, best for cross-referential reasoning.
- `markdown` — leaner prose digest.
- `json` — raw bytes of `project.json`. Use when you want to operate
  on the project structurally.

Always read once at session start before answering data-model
questions.

## Folder scan for joins

`aimm_scan_folder_for_joins({folder, dialect?, max_files?})` walks a
local directory of `.sql` files, parses each with sqlglot (multi-
dialect fallback: configured → tsql → spark → none), and writes
canonical join edges to `discovered_joins.json`. Doesn't touch
`project.json`. Useful for: "what tables join to what in this repo
of analytics queries?"

## Pending changes (deploy check)

`aimm_get_pending_changes({table?, force?})` — diff between authored
columns (in `project.json`) and the live `information_schema` shape.
Surfaces added / removed / type-changed columns per table. Use
before promoting views.

## Diagnostics

`aimm_show_diagnostics_log({max_bytes?})` returns the tail of
`diagnostics.log` where every ODBC query the server ran is recorded
with timing, DSN, and result. Use when a tool returns
`connect_failed` / `query_failed` and you want the SQL.

## Hard constraints

- Never enumerate every schema/table just to "see what's there." Ask
  the user which domain matters first.
- Never batch-write more than ~5 tables / relationships without
  confirming the plan.
- Never invent connections, PKs, FKs, or lineage the user hasn't
  sanctioned.
- Never edit `~/Documents/AIMM/project.json` directly. The `aimm_*`
  tools validate via pydantic and write atomically; direct edits
  bypass that.
